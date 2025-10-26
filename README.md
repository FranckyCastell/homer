# Homer CLI

Homer es una herramienta CLI para estandarizar y automatizar flujos de trabajo de Infraestructura como Código (IaC).

## 📋 Requisitos Previos

Para usar Homer, necesitas tener instalado en tu sistema:

- Terraform
- Packer
- Python 3.8+
- jq (requerido para el modo interactivo)

## 🚀 Instalación

El proceso de instalación está gestionado a través del comando `make`.

```bash
# Construye el paquete de distribución
make build

# Instala el comando homer en tu sistema
sudo make install
```

Una vez instalado, el comando `homer` estará disponible globalmente. Puedes verificar la instalación con `homer -h`.

## 💻 Uso

La sintaxis de Homer es flexible y permite ejecutar comandos de dos maneras: `homer <comando> <objetivo>` o `homer <objetivo> <comando>`.

### Comandos Disponibles

| Comando | Alias | Descripción |
|---------|-------|-------------|
| `init <entorno>` | - | Inicializa el backend de Terraform en el entorno especificado. |
| `plan <entorno>` | `p` | Genera un plan de cambios. Acepta `-i` para modo interactivo. |
| `apply <entorno>` | `a` | Aplica los cambios de Terraform en el entorno. |
| `destroy <entorno>` | `d` | Destruye la infraestructura. Acepta `-i` para modo interactivo. |
| `unlock <entorno>` | `u` | Libera un lock del estado de Terraform de forma segura. |
| `build <app>` | `b` | Construye una imagen de Packer a partir de una plantilla de aplicación. |

### Ejemplos de Uso

```bash
# Planificar cambios en el entorno 'pre' de forma interactiva
homer pre plan -i

# Aplicar cambios en el entorno 'pro'
homer pro apply

# Construir la imagen de 'webapp' pasando una variable a Packer
homer build webapp -- -var="ami_version=1.2.3"
```

## 🏗️ Estructura del Proyecto

```
/homer/
├── .gitignore          # Ficheros ignorados por Git
├── main.py             # Punto de entrada de la CLI
├── Makefile            # Comandos para build, install, clean, etc.
├── pyproject.toml      # Definición del proyecto y sus dependencias
├── README.md           # Esta documentación
└── libs/
    ├── __init__.py     # Inicializador del módulo libs
    ├── core.py         # Lógica principal (TerraformManager, PackerManager)
    ├── exceptions.py   # Clases de excepciones personalizadas
    └── utils.py        # Utilidades (colores, etc.)
```

## 🛠️ Mantenimiento

```bash
# Limpieza completa del entorno de desarrollo
make clean
```