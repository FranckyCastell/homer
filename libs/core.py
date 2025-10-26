from __future__ import annotations
from pathlib import Path
from typing import List, Optional, Sequence, Tuple
import argparse, json, os, re, shutil, signal, subprocess, sys

from libs.exceptions import CommandExecutionError
from libs.utils import Colors, TempFileManager, TERRAFORM_FILE_GLOB, get_terraform_version

# --- Constantes ---
TEMP_PLAN_FILENAME = "tmp.tfplan"
PACKER_APP_DIR = "amis"
PACKER_FILE_GLOB = "*.pkr.hcl"


# --- Gestión de Procesos ---
class TerraformProcessManager:
    """Gestiona la ejecución de comandos de Terraform con un manejo robusto de señales."""

    def __init__(self):
        self.current_process: Optional[subprocess.Popen] = None
        self.interrupt_count = 0

    def _signal_handler(self, signum, frame):
        self.interrupt_count += 1
        if not self.current_process or self.current_process.poll() is not None:
            return

        if self.interrupt_count == 1:
            print(f"\n{Colors.warning('Interrupción detectada. Enviando señal a Terraform para un cierre seguro...')}")
            try:
                if sys.platform != "win32":
                    os.killpg(os.getpgid(self.current_process.pid), signal.SIGINT)
                else:
                    self.current_process.send_signal(signal.SIGINT)
            except ProcessLookupError:
                pass # El proceso ya ha terminado
        elif self.interrupt_count >= 2:
            print(f"\n{Colors.fail('Forzando terminación inmediata...')}")
            try:
                self.current_process.kill()
            except ProcessLookupError:
                pass # El proceso ya ha terminado

    def run_command(self, command: List[str], cwd: Path, capture: bool = False) -> subprocess.CompletedProcess:
        original_sigint = signal.signal(signal.SIGINT, self._signal_handler)
        original_sigterm = signal.signal(signal.SIGTERM, self._signal_handler)
        self.interrupt_count = 0

        try:
            preexec_fn = None if sys.platform == "win32" else os.setsid
            self.current_process = subprocess.Popen(
                command, cwd=str(cwd), stdout=subprocess.PIPE if capture else None,
                stderr=subprocess.PIPE if capture else None, text=True, encoding="utf-8", preexec_fn=preexec_fn
            )
            stdout, stderr = self.current_process.communicate()
            returncode = self.current_process.returncode

            if self.interrupt_count > 0:
                raise KeyboardInterrupt("Proceso interrumpido por el usuario.")
            if returncode != 0:
                raise CommandExecutionError(f"El comando `{' '.join(command)}` falló.", returncode, stdout, stderr)

            return subprocess.CompletedProcess(args=command, returncode=returncode, stdout=stdout, stderr=stderr)
        finally:
            self.current_process = None
            signal.signal(signal.SIGINT, original_sigint)
            signal.signal(signal.SIGTERM, original_sigterm)


# --- Clases de Flujo de Trabajo Especializadas de Terraform ---

class TerraformUnlocker:
    """Gestiona el flujo de trabajo de desbloqueo de Terraform."""
    def __init__(self, process_manager: TerraformProcessManager, env_path: Path):
        self.process_manager = process_manager
        self.env_path = env_path

    def _run_tf_command(self, command: List[str], capture: bool = False) -> subprocess.CompletedProcess:
        return self.process_manager.run_command(["terraform", *command], self.env_path, capture)

    def run(self):
        _print_header(f"Verificación de Locks - Entorno: {self.env_path.name}")
        try:
            self._run_tf_command(["plan", "-input=false"])
            print(f"{Colors.success('No se detectaron locks activos.')}")
        except CommandExecutionError as e:
            if "Error acquiring the state lock" in e.stderr:
                print(f"{Colors.warning('Se ha detectado un lock de Terraform.')}")
                lock_id_match = re.search(r"ID:\s*([a-f0-9-]+)", e.stderr)
                lock_id = lock_id_match.group(1) if lock_id_match else None
                if lock_id:
                    print(f"  - Lock ID: {lock_id}")
                
                if input("¿Forzar desbloqueo? (s/N): ").strip().lower() == 's':
                    if not lock_id:
                        lock_id = input("Introduce el Lock ID manualmente: ").strip()
                    if lock_id:
                        self._run_tf_command(["force-unlock", "-force", lock_id])
                        print(f"{Colors.success('Lock liberado.')}")
            else:
                print(f"{Colors.fail('Error inesperado al comprobar los locks:')}")
                print(e.stderr)

class TerraformInteractiveRunner:
    """Gestiona el flujo de trabajo interactivo para plan y destroy."""
    def __init__(self, process_manager: TerraformProcessManager, temp_manager: TempFileManager, env_path: Path, command: str, extra_args: List[str]):
        self.process_manager = process_manager
        self.temp_manager = temp_manager
        self.env_path = env_path
        self.command = command
        self.extra_args = extra_args

    def _run_tf_command(self, command: List[str], capture: bool = False) -> subprocess.CompletedProcess:
        return self.process_manager.run_command(["terraform", *command], self.env_path, capture)

    def run(self):
        _check_dependencies(["jq"])
        _print_header(f"Modo Interactivo ({self.command}) - Entorno: {self.env_path.name}")

        is_destroy = self.command == "destroy"
        changes = self._get_plan_changes(destroy_plan=is_destroy)

        if not changes:
            print(f"{Colors.success('El plan no contiene cambios. No hay nada que hacer.')}")
            return

        self._display_changes(changes)
        self._prompt_for_selection(changes)

    def _get_plan_changes(self, destroy_plan: bool) -> List[Tuple[str, str]]:
        plan_file = self.temp_manager.get_temp_path(TEMP_PLAN_FILENAME)
        plan_command = ["plan", "-out", str(plan_file), *self.extra_args]
        if destroy_plan:
            plan_command.append("-destroy")

        self._run_tf_command(plan_command)
        show_result = self._run_tf_command(["show", "-json", str(plan_file)], capture=True)
        plan_data = json.loads(show_result.stdout)

        return [
            (res.get("address", ""), ",".join(res.get("change", {}).get("actions", [])))
            for res in plan_data.get("resource_changes", [])
            if "no-op" not in res.get("change", {}).get("actions", [])
        ]

    def _display_changes(self, changes: List[Tuple[str, str]]):
        print(f"\nCambios de recursos propuestos:")
        for i, (address, actions) in enumerate(changes, 1):
            color = Colors.fail if "delete" in actions else Colors.success if "create" in actions else Colors.warning
            print(f"  {i:2d}) {color(f'{address} ({actions})')}")

    def _prompt_for_selection(self, changes: List[Tuple[str, str]]):
        try:
            choice = input(f"\nElige un recurso (1-{len(changes)}), 't' para todos, o 'c' para cancelar: ").strip().lower()
            if choice in ("c", "cancelar"):
                return

            final_command = "apply" if self.command == "plan" else "destroy"

            if choice in ("t", "todos"):
                plan_file = self.temp_manager.get_temp_path(TEMP_PLAN_FILENAME)
                self._run_tf_command([final_command, "-auto-approve", str(plan_file)])
                return

            index = int(choice)
            if 1 <= index <= len(changes):
                target = f"-target={changes[index - 1][0]}"
                if input(f"¿Confirmas la operación '{final_command}' para el recurso seleccionado? (s/N): ").strip().lower() == 's':
                    self._run_tf_command([final_command, "-auto-approve", target, *self.extra_args])
            else:
                raise ValueError("Selección inválida.")
        except (ValueError, KeyboardInterrupt) as e:
            print(f"\n{Colors.fail(f'Operación cancelada. {e}')}")


# --- Clases Facade y Gestoras ---

class TerraformManager:
    """Fachada para todas las operaciones de Terraform."""

    def __init__(self, project_root: Path, process_manager: TerraformProcessManager, temp_manager: TempFileManager):
        self.project_root = project_root
        self.process_manager = process_manager
        self.temp_manager = temp_manager

    def _run_tf_command(self, command: List[str], cwd: Path, capture: bool = False) -> subprocess.CompletedProcess:
        return self.process_manager.run_command(["terraform", *command], cwd, capture=capture)

    def get_current_version(self) -> Optional[str]:
        """Obtiene la versión de Terraform activa ejecutando `terraform version -json`."""
        try:
            # Usamos el project_root como un directorio base seguro para ejecutar el comando.
            result = self._run_tf_command(["version", "-json"], cwd=self.project_root, capture=True)
            version_data = json.loads(result.stdout)
            return version_data.get("terraform_version")
        except (CommandExecutionError, FileNotFoundError, json.JSONDecodeError) as e:
            # Si terraform no está instalado o falla, no podemos obtener la versión.
            # Se imprime un aviso y se devuelve None para omitir la comprobación.
            print(f"{Colors.warning('AVISO:')} No se pudo determinar la versión de Terraform. Se omitirá la comprobación. Error: {e}", file=sys.stderr)
            return None

    def _validate_environment(self, environment: str) -> Path:
        if not environment:
            raise ValueError("Se debe especificar un entorno.")
        env_path = self.project_root / environment
        if not (env_path.is_dir() and any(env_path.glob(TERRAFORM_FILE_GLOB))):
            raise ValueError(f"El entorno '{environment}' no es válido o no contiene ficheros {TERRAFORM_FILE_GLOB}.")
        return env_path

    def _ensure_terraform_init(self, env_path: Path):
        self._run_tf_command(["init", "-input=false", "-reconfigure"], cwd=env_path)
    
    def get_available_environments(self) -> List[str]:
        """Encuentra todos los entornos de Terraform válidos en la raíz del proyecto."""
        if not self.project_root.is_dir():
            return []
        return sorted(
            [
                item.name
                for item in self.project_root.iterdir()
                if item.is_dir() and not item.name.startswith(".") and any(item.glob(TERRAFORM_FILE_GLOB))
            ]
        )

    def init(self, environment: str, extra_args: List[str]):
        env_path = self._validate_environment(environment)
        _print_header(f"Terraform Init - Entorno: {environment}")
        self._run_tf_command(["init", *extra_args], cwd=env_path)

    def plan(self, environment: str, interactive: bool, extra_args: List[str]):
        env_path = self._validate_environment(environment)
        self._ensure_terraform_init(env_path)
        if interactive:
            runner = TerraformInteractiveRunner(self.process_manager, self.temp_manager, env_path, "plan", extra_args)
            runner.run()
        else:
            _print_header(f"Terraform Plan - Entorno: {environment}")
            self._run_tf_command(["plan", *extra_args], cwd=env_path)

    def apply(self, environment: str, extra_args: List[str]):
        env_path = self._validate_environment(environment)
        self._ensure_terraform_init(env_path)
        _print_header(f"Terraform Apply - Entorno: {environment}")
        self._run_tf_command(["apply", *extra_args], cwd=env_path)

    def destroy(self, environment: str, interactive: bool, extra_args: List[str]):
        env_path = self._validate_environment(environment)
        self._ensure_terraform_init(env_path)
        if interactive:
            runner = TerraformInteractiveRunner(self.process_manager, self.temp_manager, env_path, "destroy", extra_args)
            runner.run()
        else:
            _print_header(f"Terraform Destroy - Entorno: {environment}")
            self._run_tf_command(["destroy", *extra_args], cwd=env_path)

    def unlock(self, environment: str):
        env_path = self._validate_environment(environment)
        unlocker = TerraformUnlocker(self.process_manager, env_path)
        unlocker.run()

class PackerManager:
    """Gestiona todas las operaciones de Packer."""

    def __init__(self, project_root: Path):
        self.project_root = project_root

    def _run_packer_command(self, command: List[str], cwd: Path):
        subprocess.run(["packer", *command], cwd=str(cwd), check=True)

    def get_available_apps(self) -> List[str]:
        """Encuentra todas las aplicaciones de Packer válidas."""
        amis_dir = self.project_root / PACKER_APP_DIR
        if not amis_dir.is_dir():
            return []
        return sorted(
            [
                item.name
                for item in amis_dir.iterdir()
                if item.is_dir() and any(item.glob(PACKER_FILE_GLOB))
            ]
        )

    def build(self, app: str, extra_args: List[str]):
        if not app:
            raise ValueError("Se debe especificar una aplicación para construir.")
        app_path = self.project_root / PACKER_APP_DIR / app
        if not app_path.is_dir():
            raise FileNotFoundError(f"El directorio de la aplicación '{app}' no se encontró en '{app_path.parent}'.")
        if not any(app_path.glob(PACKER_FILE_GLOB)):
            raise FileNotFoundError(f"No se encontraron ficheros '{PACKER_FILE_GLOB}' en '{app_path}'.")
        
        _print_header(f"Packer Build - App: {app}")
        self._run_packer_command(["init", "."], cwd=app_path)
        self._run_packer_command(["build", *extra_args, "."], cwd=app_path)


class CLIHandler:
    """Gestiona el análisis de argumentos y orquesta la ejecución de los flujos de trabajo."""

    def __init__(self, project_root: Path):
        self.project_root = project_root
        self.temp_manager = TempFileManager()
        tf_process_manager = TerraformProcessManager()
        self.tf_manager = TerraformManager(project_root, tf_process_manager, self.temp_manager)
        self.packer_manager = PackerManager(project_root)
        
        self._check_terraform_version()

        self.handler_map = {
            "init": self.tf_manager.init,
            "plan": self.tf_manager.plan,
            "p": self.tf_manager.plan,
            "apply": self.tf_manager.apply,
            "a": self.tf_manager.apply,
            "destroy": self.tf_manager.destroy,
            "d": self.tf_manager.destroy,
            "unlock": self.tf_manager.unlock,
            "u": self.tf_manager.unlock,
            "build": self.packer_manager.build,
            "b": self.packer_manager.build,
        }

    def _check_terraform_version(self):
        """Comprueba si la versión de Terraform activa coincide con la de .terraform-version."""
        required_version = get_terraform_version(self.project_root)
        if not required_version:
            return  # No hay fichero .terraform-version, no hay nada que hacer.

        current_version = self.tf_manager.get_current_version()
        if not current_version:
            return # No se pudo obtener la versión actual, se omite la comprobación.

        if current_version != required_version:
            print(f"{Colors.warning('AVISO:')} La versión de Terraform ({current_version}) no es la misma que la requerida por .terraform-version ({required_version}).")
            print(f"{Colors.info('Por favor, ejecute \'tfenv install\' para instalar la versión correcta.')}")
            sys.exit(1)

    def run(self, cli_args: Sequence[str]):
        if len(cli_args) < 2:
            _print_help()
            return

        arg1, arg2 = cli_args[0], cli_args[1]
        remaining_args = cli_args[2:]

        available_envs = self.tf_manager.get_available_environments()
        available_apps = self.packer_manager.get_available_apps()
        
        action, target = None, None

        if arg1 in self.handler_map and (arg2 in available_envs or arg2 in available_apps):
            action, target = self.handler_map[arg1], arg2
        elif arg2 in self.handler_map and (arg1 in available_envs or arg1 in available_apps):
            action, target = self.handler_map[arg2], arg1
        
        if not action:
            raise ValueError(f"Combinación de comando y objetivo no válida: '{arg1}', '{arg2}'.")

        # Análisis manual de flags y argumentos extra
        interactive = "-i" in remaining_args or "--interactive" in remaining_args
        if interactive:
            remaining_args = [arg for arg in remaining_args if arg not in ("-i", "--interactive")]

        try:
            extra_args_pos = remaining_args.index('--')
            extra_args = remaining_args[extra_args_pos + 1:]
        except ValueError:
            extra_args = []

        kwargs = {"extra_args": extra_args}
        if target in available_envs:
            kwargs["environment"] = target
            # Comprobar si la acción puede ser interactiva
            if action.__name__ in ["plan", "destroy"]:
                kwargs["interactive"] = interactive
        elif target in available_apps:
            kwargs["app"] = target

        # Llamar al manejador con los argumentos correctos
        action(**kwargs)

    def cleanup(self):
        self.temp_manager.cleanup()

# --- Funciones Auxiliares ---
def _print_header(message: str):
    print(f"\n{'='*60}\n# {Colors.bold(Colors.header(message))}\n{'='*60}")

def _check_dependencies(deps: List[str]):
    missing = [dep for dep in deps if not shutil.which(dep)]
    if missing:
        raise FileNotFoundError(f"Dependencias requeridas no encontradas: {', '.join(missing)}")

def _print_help():
    banner = """
██╗░░██╗░█████╗░███╗░░███╗███████╗██████╗
██║░░██║██╔══██╗████╗████║██╔════╝██╔══██╗
███████║██║░░██║██╔███╔██║█████╗░░██████╔╝
██╔══██║██╔══██║██║╚█╔╝██║██╔══╝░░██╔══██╗
██║░░██║░█████╗░██║░╚═╝░██║███████╗██║░░██║
╚═╝░░╚═╝░╚════╝░╚═╝░░░░░╚═╝╚══════╝╚═╝░░╚═╝
"""
    header = "HOMER-CLI: Herramienta de Automatización para IaC"
    help_text = f"""
{Colors.bold(Colors.header(header))}
{'-' * len(header)}
Herramienta para optimizar y automatizar tareas de IaC con Terraform y Packer.

{Colors.warning(Colors.bold('USO'))}
  homer <comando> <objetivo> [opciones]
  homer <objetivo> <comando> [opciones]

{Colors.warning(Colors.bold('COMANDOS'))}
  {'init'.ljust(20)} Inicializa el backend de Terraform en un entorno.
  {'plan (p)'.ljust(20)} Genera un plan de cambios de Terraform.
  {'apply (a)'.ljust(20)} Aplica los cambios de un plan de Terraform.
  {'destroy (d)'.ljust(20)} Destruye la infraestructura de un entorno.
  {'unlock (u)'.ljust(20)} Libera un 'lock' del estado de Terraform.
  {'build (b)'.ljust(20)} Construye una imagen de Packer para una aplicación.

{Colors.warning(Colors.bold('OPCIONES'))}
  {'-i, --interactive'.ljust(20)} Activa el modo interactivo para 'plan' y 'destroy'.
"""
    print(Colors.header(banner))
    print(help_text)
