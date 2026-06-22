import os
from typing import Optional, List

try:
    from github import Github
    HAS_GITHUB = True
except ImportError:
    HAS_GITHUB = False
    class Github:
        def __init__(self, *args, **kwargs):
            pass
        def get_repo(self, *args, **kwargs):
            raise ImportError("La librería 'PyGithub' no está instalada. Ejecuta 'pip install PyGithub' para usar esta función.")

# Intentamos importar FastMCP de forma segura
try:
    from mcp.server.fastmcp import FastMCP
except ImportError:
    try:
        from fastmcp import FastMCP
    except ImportError:
        # Mock en caso de que no esté instalado en el entorno de ejecución
        class FastMCP:
            def __init__(self, name: str):
                self.name = name
            def tool(self):
                def decorator(func):
                    return func
                return decorator
            def run(self):
                print(f"[*] MCP Server '{self.name}' mock running.")

mcp = FastMCP("github-reader-server")

def _get_github_client(token: Optional[str] = None) -> Github:
    """
    Retorna una instancia autenticada o anónima de PyGithub.
    """
    t = token or os.environ.get("GITHUB_TOKEN")
    if t:
        return Github(t)
    return Github()

@mcp.tool()
def read_github_file(repo_name: str, path: str, branch: str = "main", token: Optional[str] = None) -> str:
    """
    Lee el contenido de un archivo de texto de un repositorio de GitHub.
    
    Parámetros:
    - repo_name: Nombre del repositorio en formato 'propietario/nombre' (ej. 'octocat/Hello-World')
    - path: Ruta del archivo dentro del repositorio (ej. 'README.md')
    - branch: Rama a consultar (por defecto 'main')
    - token: Token de acceso personal de GitHub (opcional)
    """
    try:
        g = _get_github_client(token)
        repo = g.get_repo(repo_name)
        content_file = repo.get_contents(path, ref=branch)
        
        # Si es una lista, es un directorio, no un archivo
        if isinstance(content_file, list):
            raise ValueError(f"La ruta '{path}' es un directorio, no un archivo.")
            
        # El contenido viene codificado en base64
        return content_file.decoded_content.decode("utf-8")
    except Exception as e:
        return f"Error leyendo el archivo '{path}' en '{repo_name}': {str(e)}"

@mcp.tool()
def list_github_directory(repo_name: str, path: str = "", branch: str = "main", token: Optional[str] = None) -> List[str]:
    """
    Lista el contenido de un directorio en un repositorio de GitHub.
    
    Parámetros:
    - repo_name: Nombre del repositorio en formato 'propietario/nombre'
    - path: Ruta de la carpeta (por defecto es la raíz '')
    - branch: Rama a consultar (por defecto 'main')
    - token: Token de acceso personal de GitHub (opcional)
    """
    try:
        g = _get_github_client(token)
        repo = g.get_repo(repo_name)
        contents = repo.get_contents(path, ref=branch)
        
        if not isinstance(contents, list):
            return [contents.path]
            
        items = []
        for item in contents:
            item_type = "DIR" if item.type == "dir" else "FILE"
            items.append(f"[{item_type}] {item.path}")
        return items
    except Exception as e:
        return [f"Error listando el directorio '{path}' en '{repo_name}': {str(e)}"]

if __name__ == "__main__":
    mcp.run()
