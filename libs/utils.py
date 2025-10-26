import os, sys, shutil, tempfile, subprocess, json
from pathlib import Path
from typing import List, Optional

TERRAFORM_ROOT_SUBDIRS = ["terraform"]
TERRAFORM_FILE_GLOB = "*.tf"

class Colors:

    HEADER = "\033[95m"
    OKBLUE = "\033[94m"
    OKGREEN = "\033[92m"
    WARNING = "\033[93m"
    FAIL = "\033[91m"
    ENDC = "\033[0m"
    BOLD = "\033[1m"
    _enabled = sys.stdout.isatty()

    @classmethod
    def enable(cls, enabled: bool):
        cls._enabled = enabled

    @classmethod
    def _colorize(cls, color_code: str, message: str) -> str:
        return f"{color_code}{message}{cls.ENDC}" if cls._enabled else message

    @classmethod
    def header(cls, msg: str) -> str:
        return cls._colorize(cls.HEADER, msg)

    @classmethod
    def info(cls, msg: str) -> str:
        return cls._colorize(cls.OKBLUE, msg)

    @classmethod
    def success(cls, msg: str) -> str:
        return cls._colorize(cls.OKGREEN, msg)

    @classmethod
    def warning(cls, msg: str) -> str:
        return cls._colorize(cls.WARNING, msg)

    @classmethod
    def fail(cls, msg: str) -> str:
        return cls._colorize(cls.FAIL, msg)

    @classmethod
    def bold(cls, msg: str) -> str:
        return cls._colorize(cls.BOLD, msg)

class TempFileManager:

    def __init__(self):
        self.temp_dir = Path(tempfile.mkdtemp(prefix="make-cli-"))

    def get_temp_path(self, filename: str) -> Path:
        return self.temp_dir / filename

    def cleanup(self):
        if self.temp_dir and self.temp_dir.exists():
            try:
                shutil.rmtree(self.temp_dir)
            except OSError as e:
                print(
                    f"{Colors.warning('AVISO:')} No se pudo eliminar el directorio temporal {self.temp_dir}: {e}",
                    file=sys.stderr,
                )

def _is_valid_tf_root(path: Path) -> bool:
    """Comprueba si una ruta es una raíz de proyecto de Terraform válida."""
    if not path.is_dir():
        return False
    return any(
        (d.is_dir() and any(d.glob(TERRAFORM_FILE_GLOB)))
        for d in path.iterdir()
        if d.is_dir() and not d.name.startswith(".")
    )

def find_project_root() -> Path:
    """
    Busca el directorio raíz del proyecto subiendo desde el directorio actual.
    Un directorio raíz válido contiene subdirectorios con archivos .tf.
    """
    current_path = Path.cwd().resolve()
    while current_path != current_path.parent:
        if _is_valid_tf_root(current_path):
            return current_path

        for subdir_name in TERRAFORM_ROOT_SUBDIRS:
            potential_root = current_path / subdir_name
            if _is_valid_tf_root(potential_root):
                return potential_root

        current_path = current_path.parent

    raise FileNotFoundError("No se pudo encontrar el directorio raíz del proyecto con entornos de Terraform.")

def get_terraform_version(start_path: Path) -> Optional[str]:
    """
    Busca y lee la versión de Terraform desde un fichero .terraform-version,
    subiendo desde el directorio actual.
    """
    current_path = start_path.resolve()
    while current_path != current_path.parent:
        version_file = current_path / ".terraform-version"
        if version_file.is_file():
            try:
                version = version_file.read_text(encoding="utf-8").strip()
                if version:
                    return version
            except Exception as e:
                print(f"{Colors.warning('AVISO:')} No se pudo leer el fichero {version_file}: {e}", file=sys.stderr)
                return None # Si hay un error de lectura, no podemos comparar.
        current_path = current_path.parent
    return None