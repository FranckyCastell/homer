import signal
import sys
import traceback
import argparse

from libs.core import CLIHandler, _print_help
from libs.exceptions import CommandExecutionError
from libs.utils import Colors, find_project_root

def main() -> int:
    """
    Punto de entrada principal de la aplicación.
    """
    # Manejo de la ayuda globalmente, antes de cualquier otra lógica
    if "-h" in sys.argv[1:] or "--help" in sys.argv[1:]:
        _print_help()
        return 0

    # Manejo preliminar de --no-color para desactivar colores globalmente
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--no-color", action="store_true", help="Desactiva la salida con colores.")
    args, remaining_args = parser.parse_known_args(sys.argv[1:])

    if args.no_color:
        Colors.enable(False)

    cli = None
    exit_code = 0

    def signal_handler(signum, frame):
        """Manejador de señales para una limpieza ordenada."""
        print(Colors.warning("\nScript interrumpido. Realizando limpieza..."))
        if cli:
            cli.cleanup()
        sys.exit(130)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    try:
        project_root = find_project_root()
        cli = CLIHandler(project_root)
        cli.run(remaining_args)
        print(f"\n{'='*20} {Colors.success('Operación completada con éxito')} {'='*20}\n")

    except KeyboardInterrupt:
        exit_code = 130  # Código de salida estándar para Ctrl+C

    except FileNotFoundError as e:
        print(f"{Colors.fail('ERROR:')} {e}", file=sys.stderr)
        print(f"\n{Colors.info('Asegúrese de estar en un directorio de proyecto válido o en uno de sus subdirectorios.')}", file=sys.stderr)
        print(f"{Colors.info('Para ver la ayuda en cualquier momento, ejecute: homer -h')}", file=sys.stderr)
        exit_code = 1

    except (CommandExecutionError, ValueError) as e:
        print(f"{Colors.fail('ERROR:')} {e}", file=sys.stderr)
        if isinstance(e, CommandExecutionError):
            if e.stdout:
                print(f"{Colors.fail('--- STDOUT ---')}\n{e.stdout.strip()}")
            if e.stderr:
                print(f"{Colors.fail('--- STDERR ---')}\n{e.stderr.strip()}")
        exit_code = 1
        print(f"\n{'='*20} {Colors.fail('La operación falló')} {'='*20}\n")

    except Exception as e:
        print(f"{Colors.fail('ERROR INESPERADO:')} Se ha producido un error no controlado: {e}", file=sys.stderr)
        traceback.print_exc()
        exit_code = 1
        print(f"\n{'='*20} {Colors.fail('La operación falló')} {'='*20}\n")

    finally:
        if cli:
            cli.cleanup()

    return exit_code

if __name__ == "__main__":
    sys.exit(main())