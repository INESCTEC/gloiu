
import os, requests

LLAMA_BACKEND = os.getenv("LLAMA_BACKEND", "OLLAMA").upper()
LLAMA_MODEL = os.getenv("LLAMA_MODEL", "llama3.2")
LLAMA_ENDPOINT = os.getenv("LLAMA_ENDPOINT", "http://localhost:11434")

def generate_text(system: str, prompt: str, max_tokens: int = 512, temperature: float = 0.2) -> str:
    if LLAMA_BACKEND == "OLLAMA":
        url = f"{LLAMA_ENDPOINT}/api/chat"
        payload = {
            "model": LLAMA_MODEL,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt}
            ],
            "stream": False,
            "options": {"temperature": temperature, "num_predict": max_tokens}
        }
        r = requests.post(url, json=payload, timeout=120); r.raise_for_status()
        return r.json().get("message", {}).get("content", "")

    elif LLAMA_BACKEND == "VLLM":
        url = f"{LLAMA_ENDPOINT}/v1/chat/completions"
        payload = {
            "model": LLAMA_MODEL,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt}
            ],
            "max_tokens": max_tokens,
            "temperature": temperature
        }
        r = requests.post(url, json=payload, timeout=120); r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]

    elif LLAMA_BACKEND == "TGI":
        url = f"{LLAMA_ENDPOINT}/generate"
        full_prompt = f"<<SYS>>{system}<<SYS>>\n{prompt}"
        payload = {"inputs": full_prompt, "parameters": {"max_new_tokens": max_tokens, "temperature": temperature}}
        r = requests.post(url, json=payload, timeout=120); r.raise_for_status()
        return r.json()["generated_text"]

    else:
        raise RuntimeError(f"Unsupported LLAMA_BACKEND: {LLAMA_BACKEND}")
