import sys
import re
import json

def check_lang(html_str):
    # Encontrar <html ...> ignorando mayúsculas y espacios
    match = re.search(r'<html([^>]+)>', html_str, re.IGNORECASE)
    if not match:
        # Puede que sea solo <html> sin atributos
        if re.search(r'<html>', html_str, re.IGNORECASE):
            return {"presente": False, "valor": None, "valido": False}
        # Si no hay etiqueta html, devolvemos un estado seguro
        return {"presente": False, "valor": None, "valido": False}
    
    attrs_str = match.group(1)
    
    # Encontrar lang="..." o lang='...'
    lang_match = re.search(r'lang\s*=\s*["\']([^"\']*)["\']', attrs_str, re.IGNORECASE)
    if not lang_match:
        return {"presente": False, "valor": None, "valido": False}
        
    lang_val = lang_match.group(1).strip()
    
    if not lang_val:
        return {"presente": True, "valor": "", "valido": False}
    
    # Validar formato BCP 47 muy básico (ej. 'es', 'en-US', 'es-419')
    # Dos o tres letras minúsculas, opcionalmente un guion y subtags
    valido = bool(re.match(r'^[a-zA-Z]{2,3}(-[a-zA-Z0-9]+)*$', lang_val))
    
    return {"presente": True, "valor": lang_val, "valido": valido}

if __name__ == "__main__":
    # Leer el HTML desde la entrada estándar
    html_input = sys.stdin.read()
    if not html_input.strip():
        print(json.dumps({"error": "No input provided"}))
        sys.exit(1)
        
    result = check_lang(html_input)
    print(json.dumps({"issue": result}, indent=2))
