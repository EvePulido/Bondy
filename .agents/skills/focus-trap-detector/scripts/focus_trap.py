import sys
import json
import tempfile
import os
from playwright.sync_api import sync_playwright

def detect_focus_trap(content):
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        
        is_file = False
        temp_path = None
        
        if content.startswith('http://') or content.startswith('https://'):
            page.goto(content)
        else:
            fd, temp_path = tempfile.mkstemp(suffix='.html')
            with os.fdopen(fd, 'w', encoding='utf-8') as f:
                f.write(content)
            page.goto(f'file://{temp_path}')
            is_file = True
            
        focus_sequence = []
        
        # Simular 30 tabs
        for _ in range(30):
            page.keyboard.press("Tab")
            
            sel = page.evaluate("""() => {
                const el = document.activeElement;
                if (!el || el === document.body) return null;
                let s = el.tagName.toLowerCase();
                if (el.id) s += '#' + el.id;
                return s;
            }""")
            
            if sel:
                focus_sequence.append(sel)
                
        browser.close()
        
        if is_file and temp_path:
            try:
                os.remove(temp_path)
            except:
                pass
                
        # Detectar ciclo
        trap = False
        unique_elements = set(focus_sequence[-10:]) if len(focus_sequence) >= 10 else set(focus_sequence)
        
        # Si de los últimos 10 tabs, el foco está oscilando entre un conjunto muy pequeño de elementos (2 o 3) y no sale de ahí.
        if len(focus_sequence) >= 30 and len(unique_elements) > 0 and len(unique_elements) <= 3:
            # Hay que verificar si es realmente un bucle. Para el mock, asumimos que si cicla en < 3 elementos en los últimos 10 tabs, es trampa.
            trap = True
            
        return {
            "trampa_detectada": trap,
            "selectores_involucrados": list(unique_elements),
            "num_pulsaciones_sin_salida": 30 if trap else 0
        }

if __name__ == "__main__":
    content = sys.stdin.read()
    if not content.strip():
        print(json.dumps({"error": "No input provided"}))
        sys.exit(1)
        
    result = detect_focus_trap(content)
    print(json.dumps(result, indent=2))
