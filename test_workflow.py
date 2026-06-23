import asyncio
from dotenv import load_dotenv
load_dotenv(override=True)

from google.adk.runners import InMemoryRunner
from google.genai import types
from app.agent import app as adk_app

async def main():
    runner = InMemoryRunner(app=adk_app)
    session = await runner.session_service.create_session(app_name="app", user_id="test")
    prompt = "Ejecuta una auditoría de accesibilidad para la ruta/source: demo_sites/site_1_bad_alt"
    
    try:
        async for event in runner.run_async(user_id="test", session_id=session.id, new_message=types.Content(role="user", parts=[types.Part.from_text(text=prompt)])):
            if event.output is not None:
                print(f"OUTPUT FROM {event.author}: {event.output}")
            elif getattr(event, "error", None) is not None:
                print(f"ERROR FROM {event.author}: {event.error}")
            else:
                print(f"EVENT FROM {event.author}: no output")
    except Exception as e:
        print(f"EXCEPTION: {e}")

if __name__ == "__main__":
    asyncio.run(main())
