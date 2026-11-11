from core.user_paths import get_user_data_dir
import json
import logging
import requests
from pathlib import Path
from typing import Optional
from or_client import client as openrouter_client

logger = logging.getLogger("llm_client")

def _get_base_dir() -> Path:
    import sys
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent

BASE_DIR = _get_base_dir()
SETTINGS_PATH = get_user_data_dir() / "config" / "app_settings.json"

class UnifiedAIClient:
    def __init__(self):
        self._provider = "OpenRouter"
        self._local_url = "http://localhost:11434/v1"
        self._local_model = "llama3.2"
        self.reload_settings()

    def reload_settings(self):
        try:
            with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            self._provider = data.get("default_ai_provider", "OpenRouter")
            self._local_url = data.get("local_ai_url", "http://localhost:11434/v1").rstrip("/")
            self._local_model = data.get("local_ai_model", "llama3.2")
        except Exception as e:
            logger.error(f"[LLM Client] Failed to load settings: {e}")

    def _local_chat_completion(self, messages: list[dict], temperature: float = 0.7, response_format: Optional[dict] = None) -> Optional[str]:
        payload = {
            "model": self._local_model,
            "messages": messages,
            "temperature": temperature
        }
        if response_format:
            payload["response_format"] = response_format

        endpoint = f"{self._local_url}/chat/completions"
        try:
            resp = requests.post(
                endpoint,
                headers={"Content-Type": "application/json"},
                json=payload,
                timeout=120
            )
            if resp.status_code == 200:
                data = resp.json()
                content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
                return content.strip() if content else None
            else:
                logger.error(f"[LLM Client] Local AI Error {resp.status_code}: {resp.text}")
                return None
        except Exception as e:
            logger.error(f"[LLM Client] Local AI Request Failed: {e}")
            return None

    def _get_gemini_client(self):
        try:
            from google import genai
            api_keys_path = get_user_data_dir() / "config" / "api_keys.json"
            if not api_keys_path.exists():
                return None
            with open(api_keys_path, "r", encoding="utf-8") as f:
                key = json.load(f).get("gemini_api_key", "").strip()
            if not key:
                return None
            return genai.Client(api_key=key, http_options={"api_version": "v1beta"})
        except Exception as e:
            logger.error(f"[LLM Client] Failed to init Gemini client: {e}")
            return None

    def _gemini_chat_completion(self, messages: list[dict], temperature: float = 0.7, json_mode: bool = False) -> Optional[str]:
        client = self._get_gemini_client()
        if not client:
            return None
        try:
            from google.genai import types
            sys_parts = [m["content"] for m in messages if m["role"] == "system"]
            system_instruction = "\n".join(sys_parts) if sys_parts else None

            contents = []
            for m in messages:
                if m["role"] == "system":
                    continue
                role = "user" if m["role"] == "user" else "model"
                contents.append(types.Content(role=role, parts=[types.Part.from_text(text=str(m["content"]))]))

            config = types.GenerateContentConfig(
                temperature=temperature,
                system_instruction=system_instruction,
                response_mime_type="application/json" if json_mode else None
            )
            resp = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=contents,
                config=config
            )
            return resp.text.strip() if resp and resp.text else None
        except Exception as e:
            logger.error(f"[LLM Client] Gemini request failed: {e}")
            return None

    def chat(self, prompt: str, system: str = "You are a helpful assistant.", history: Optional[list[dict]] = None, model: Optional[str] = None, max_tokens: int = 4096, temperature: float = 0.7) -> str:
        self.reload_settings()
        if self._provider in ("Gemini", "Google Gemini"):
            messages = [{"role": "system", "content": system}]
            if history:
                messages.extend(history)
            messages.append({"role": "user", "content": prompt})
            result = self._gemini_chat_completion(messages, temperature)
            if result:
                return result
            try:
                return openrouter_client.chat(prompt, system, history, model, max_tokens, temperature)
            except Exception:
                pass
            return self._local_chat_completion(messages, temperature) or ""
        elif self._provider == "Local":
            messages = [{"role": "system", "content": system}]
            if history:
                messages.extend(history)
            messages.append({"role": "user", "content": prompt})
            result = self._local_chat_completion(messages, temperature)
            if result:
                return result
            else:
                raise RuntimeError("Local AI request failed. Please check if Ollama or LM Studio is running.")
        else:
            return openrouter_client.chat(prompt, system, history, model, max_tokens, temperature)

    def chat_json(self, prompt: str, system: str = "Return ONLY valid JSON.", model: Optional[str] = None, max_tokens: int = 4096) -> dict:
        self.reload_settings()
        if self._provider in ("Gemini", "Google Gemini"):
            messages = [
                {"role": "system", "content": system + " Output valid JSON only, without any markdown formatting."},
                {"role": "user", "content": prompt}
            ]
            raw = self._gemini_chat_completion(messages, temperature=0.2, json_mode=True)
            if not raw:
                try:
                    return openrouter_client.chat_json(prompt, system, model, max_tokens)
                except Exception:
                    pass
                raw = self._local_chat_completion(messages, temperature=0.2, response_format={"type": "json_object"})
            if not raw:
                raise RuntimeError("AI request failed for JSON generation.")
            
            clean = raw.strip()
            if clean.startswith("```"):
                parts = clean.split("```")
                clean = parts[1] if len(parts) > 1 else clean
                if clean.startswith("json"):
                    clean = clean[4:]
            clean = clean.strip().rstrip("`").strip()
            try:
                return json.loads(clean)
            except json.JSONDecodeError as e:
                raise ValueError(f"Gemini model returned unparseable JSON: {e}\nRaw output: {raw[:200]}")
        elif self._provider == "Local":
            messages = [
                {"role": "system", "content": system + " Output valid JSON only, without any markdown formatting."},
                {"role": "user", "content": prompt}
            ]
            raw = self._local_chat_completion(messages, temperature=0.2, response_format={"type": "json_object"})
            if not raw:
                raise RuntimeError("Local AI request failed.")
            
            clean = raw.strip()
            if clean.startswith("```"):
                parts = clean.split("```")
                clean = parts[1] if len(parts) > 1 else clean
                if clean.startswith("json"):
                    clean = clean[4:]
            clean = clean.strip().rstrip("`").strip()
            
            try:
                return json.loads(clean)
            except json.JSONDecodeError as e:
                raise ValueError(f"Local model returned unparseable JSON: {e}\nRaw output: {raw[:200]}")
        else:
            return openrouter_client.chat_json(prompt, system, model, max_tokens)

    def vision(self, prompt: str, image_b64: str, mime: str = "image/png", system: str = "Analyze the image.", model: Optional[str] = None, max_tokens: int = 1024) -> str:
        self.reload_settings()
        if self._provider in ("Gemini", "Google Gemini"):
            client = self._get_gemini_client()
            if client:
                try:
                    import base64
                    from google.genai import types
                    image_bytes = base64.b64decode(image_b64)
                    resp = client.models.generate_content(
                        model="gemini-2.5-flash",
                        contents=[
                            types.Part.from_bytes(data=image_bytes, mime_type=mime),
                            prompt
                        ],
                        config=types.GenerateContentConfig(
                            system_instruction=system,
                            max_output_tokens=max_tokens
                        )
                    )
                    if resp and resp.text:
                        return resp.text.strip()
                except Exception as e:
                    logger.error(f"[LLM Client] Gemini vision request failed: {e}")
            try:
                return openrouter_client.vision(prompt, image_b64, mime, system, model, max_tokens)
            except Exception:
                pass
            raise RuntimeError("Vision request failed with Gemini provider.")
        elif self._provider == "Local":
            messages = [
                {"role": "system", "content": system},
                {
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{image_b64}"}},
                        {"type": "text", "text": prompt}
                    ]
                }
            ]
            result = self._local_chat_completion(messages, temperature=0.2)
            if result:
                return result
            raise RuntimeError("Local AI vision request failed.")
        else:
            return openrouter_client.vision(prompt, image_b64, mime, system, model, max_tokens)

    def vision_from_file(self, prompt: str, image_path: str, system: str = "Analyze the image.", model: Optional[str] = None, max_tokens: int = 1024) -> str:
        self.reload_settings()
        if self._provider in ("Local", "Gemini", "Google Gemini"):
            import base64
            path = Path(image_path)
            mime_map = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp", ".gif": "image/gif"}
            mime = mime_map.get(path.suffix.lower(), "image/png")
            with open(path, "rb") as f:
                image_b64 = base64.b64encode(f.read()).decode("utf-8")
            return self.vision(prompt, image_b64, mime, system, model, max_tokens)
        else:
            return openrouter_client.vision_from_file(prompt, image_path, system, model, max_tokens)

    def multi_turn(self, messages: list[dict], model: Optional[str] = None, max_tokens: int = 4096, temperature: float = 0.7) -> str:
        self.reload_settings()
        if self._provider in ("Gemini", "Google Gemini"):
            result = self._gemini_chat_completion(messages, temperature)
            if result:
                return result
            try:
                return openrouter_client.multi_turn(messages, model, max_tokens, temperature)
            except Exception:
                pass
            return self._local_chat_completion(messages, temperature) or ""
        elif self._provider == "Local":
            result = self._local_chat_completion(messages, temperature)
            if result:
                return result
            raise RuntimeError("Local AI request failed.")
        else:
            return openrouter_client.multi_turn(messages, model, max_tokens, temperature)

client = UnifiedAIClient()
LLMClient = UnifiedAIClient
