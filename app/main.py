# app/main.py
from fastapi import FastAPI, Body, Response
from fastapi.responses import FileResponse, JSONResponse
from starlette.background import BackgroundTask
from dotenv import load_dotenv

import os
import json
import random
import tempfile
import re
from typing import Optional, Dict, List, Set
from datetime import datetime, timedelta

from pydantic import BaseModel, Field, validator

# ---------------- OpenAI TTS ----------------
from openai import OpenAI

# ----------------- Load .env ----------------
load_dotenv()

app = FastAPI(title="HEMS Persona Reporter", version="3.1.0")

# ================== Domain Models (inline) ==================
class DataItem(BaseModel):
    name: str
    value: float

class ScheduleSlot(BaseModel):
    # Accepts ISO strings; Pydantic will parse to datetime
    timestamp: datetime
    data: List[DataItem] = Field(default_factory=list)

class CostAnalysis(BaseModel):
    total_cost: Optional[float] = None
    total_load_cost: Optional[float] = None
    total_solar_revenue: Optional[float] = None
    currency: str = "EUR"

class OptimizationSchedule(BaseModel):
    schedule: List[ScheduleSlot] = Field(default_factory=list)
    cost_analysis: Optional[CostAnalysis] = None

    @validator("schedule")
    def _ensure_sorted(cls, v: List[ScheduleSlot]) -> List[ScheduleSlot]:
        return sorted(v, key=lambda s: s.timestamp)

# ================== Personas ==================
CHARACTERS = [
    "Master Yoda", "James Bond", "Homer Simpson", "Sherlock Holmes",
    "Darth Vader", "Harry Potter", "Captain Jack Sparrow",
    "Gandalf the Grey", "Tony Stark", "Dracula", "Elsa from Arendelle",
]

# ================== Helpers ==================
def strip_markdown(md_text: str) -> str:
    """Remove basic Markdown formatting so TTS reads clean text."""
    text = re.sub(r"\*{1,3}(.*?)\*{1,3}", r"\1", md_text)        # **bold**/*italics*
    text = re.sub(r"_{1,3}(.*?)_{1,3}", r"\1", text)              # __bold__/ _italics_
    text = re.sub(r"#+\s*", "", text)                             # headings
    text = re.sub(r"\[(.*?)\]\(.*?\)", r"\1", text)               # links [text](url)
    return text

def pick_persona(maybe_persona: Optional[str]) -> str:
    return maybe_persona.strip() if maybe_persona else random.choice(CHARACTERS)

def _guess_slot_hours(payload: "OptimizationSchedule") -> float:
    """Guess slot duration from the first two timestamps. Default 0.25h (15 min)."""
    ts = [slot.timestamp for slot in payload.schedule]
    if len(ts) >= 2:
        delta = ts[1] - ts[0]
        if isinstance(delta, timedelta) and delta.total_seconds() > 0:
            return max(delta.total_seconds() / 3600.0, 1e-9)
    return 0.25  # 15 min default

def compute_from_schedule(payload: "OptimizationSchedule"):
    """
    Returns:
      power_by_ts: dict[ts_str] -> total kW at that slot
      energy_by_load: dict[load] -> total kWh over day
      total_kwh: float
      peak_kw: float
      peak_ts: list[ts_str] where peak occurs
    """
    slot_h = _guess_slot_hours(payload)
    power_by_ts: Dict[str, float] = {}
    energy_by_load: Dict[str, float] = {}

    for slot in payload.schedule:
        ts_str = slot.timestamp.strftime("%Y-%m-%d %H:%M:%S")
        p_sum = 0.0
        for it in slot.data:
            val_kw = float(it.value)
            p_sum += val_kw
            energy_by_load[it.name] = energy_by_load.get(it.name, 0.0) + val_kw * slot_h
        power_by_ts[ts_str] = p_sum

    total_kwh = round(sum(energy_by_load.values()), 3)
    peak_kw_val = max(power_by_ts.values()) if power_by_ts else 0.0
    peak_kw = round(peak_kw_val, 3)
    peak_ts = [ts for ts, p in power_by_ts.items() if abs(p - peak_kw_val) < 1e-9]
    return power_by_ts, energy_by_load, total_kwh, peak_kw, peak_ts

def build_24h_csv(power_by_ts: Dict[str, float]) -> str:
    """
    Convert quarter-hour kW to hourly Wh sums.
    """
    per_hour_Wh: Dict[int, float] = {h: 0.0 for h in range(24)}
    for ts, p_kw in power_by_ts.items():
        hour = int(ts[11:13])
        per_hour_Wh[hour] += float(p_kw) * 0.25 * 1000.0  # 0.25h * kW -> kWh -> Wh
    lines = ["Hour,Power_W"]
    for h in range(24):
        lines.append(f"{h},{per_hour_Wh.get(h, 0.0):.1f}")
    return "\n".join(lines)

def load_windows_15m(payload: "OptimizationSchedule") -> Dict[str, List[tuple]]:
    """
    Build contiguous (start_dt, end_dt) windows per load using slot step (e.g., 15 min).
    end_dt is exclusive. Assumes schedule is sorted.
    """
    windows: Dict[str, List[tuple]] = {}
    active_start: Dict[str, datetime] = {}
    slot_h = _guess_slot_hours(payload)

    for i, slot in enumerate(payload.schedule):
        ts = slot.timestamp
        present: Set[str] = {it.name for it in slot.data}

        # close windows for loads that stop being present
        for name in list(active_start.keys()):
            if name not in present:
                windows.setdefault(name, []).append((active_start[name], ts))
                del active_start[name]

        # open windows for newly present loads
        for it in slot.data:
            if it.name not in active_start:
                active_start[it.name] = ts

        # last slot: close any active windows at +slot_h
        if i == len(payload.schedule) - 1:
            last_end = ts + timedelta(hours=slot_h)
            for name, st in active_start.items():
                windows.setdefault(name, []).append((st, last_end))
            active_start.clear()

    return windows

def fmt_range_pt(start_dt: datetime, end_dt: datetime) -> str:
    return f"{start_dt.strftime('%Hh%M')}–{end_dt.strftime('%Hh%M')}"

# ================== Health ==================
@app.get("/health")
def health():
    return {"ok": True}

# =============== LLM adapter (project function) ===============
from .llama_adapter import generate_text

# =============== Persona report (TEXT) ===============
@app.post("/persona_report")
def persona_report(payload: OptimizationSchedule = Body(...), persona: Optional[str] = None):
    # derive facts from optimized schedule (15m aware)
    power_by_ts, energy_by_load, total_kwh, peak_kw, peak_kw_ts = compute_from_schedule(payload)
    csv_24h = build_24h_csv(power_by_ts)
    hhmm = ", ".join([f"{int(ts[11:13]):02d}h{ts[14:16]}" for ts in peak_kw_ts]) if peak_kw_ts else ""

    # contiguous windows per load (15m)
    win = load_windows_15m(payload)

    # distinct power values per load (kW)
    power_values_by_load: Dict[str, Set[float]] = {}
    for slot in payload.schedule:
        for it in slot.data:
            power_values_by_load.setdefault(it.name, set()).add(float(it.value))

    # cost analysis (optional)
    ca = payload.cost_analysis
    currency = "EUR"
    total_cost = total_load_cost = total_solar_revenue = None
    if ca:
        currency = ca.currency or currency
        total_cost = ca.total_cost
        total_load_cost = ca.total_load_cost
        total_solar_revenue = ca.total_solar_revenue

    def fmt_windows(name: str) -> str:
        ranges = [fmt_range_pt(a, b) for (a, b) in win.get(name, [])]
        if not ranges:
            return ""
        if len(ranges) == 1:
            return ranges[0]
        if len(ranges) == 2:
            return " e ".join(ranges)
        return ", ".join(ranges[:-1]) + " e " + ranges[-1]

    # Build fact lines used verbatim by the LLM
    windows_lines: List[str] = []
    for name in sorted(win.keys()):
        total_e = energy_by_load.get(name, 0.0)
        pw = sorted(power_values_by_load.get(name, set()))
        rng = fmt_windows(name)
        windows_lines.append(
            f"- {name} | janela_otima={rng} | power_kW={pw} | energia_total_kWh={total_e:.1f}"
        )

    who = pick_persona(persona)

    # System prompt: PT-PT, instrutivo, sem inventar números
    system = (
        "Português (PT-PT). Clareza e objetividade. "
        "NÃO inventes números: usa apenas os dados fornecidos. "
        f"Escreve no estilo da personagem '{who}', incorporando maneirismos, frases típicas e expressões características, "
        "mas sem inventar factos técnicos nem alterar números. "
        "O conteúdo numérico e factual deve ser exato; o tom e estilo devem ser coloridos pela personagem."
    )

    # Cost lines for the narrative (optional)
    cost_lines: List[str] = []
    if total_cost is not None:
        if total_load_cost is not None and total_solar_revenue is not None:
            net = float(total_load_cost) - float(total_solar_revenue)
            cost_lines += [
                f"Custo total: {float(total_cost):.2f} {currency}",
                f"Custo dos consumos: {float(total_load_cost):.2f} {currency}",
                f"Receita solar: {float(total_solar_revenue):.2f} {currency}",
                f"Custo líquido (consumos - receita solar): {net:.2f} {currency}",
            ]
        else:
            cost_lines.append(f"Custo total: {float(total_cost):.2f} {currency}")

    # User prompt: INSTRUTIVO + custos.
    # Regras fortes: começar EXACTAMENTE com "Olá! Sou {who}, ..."
    # e incluir obrigatoriamente a secção "Custos do dia" copiando as linhas literais.
    user = (
        f"Começa EXACTAMENTE com: 'Olá! Sou {who}, e estou aqui para indicar os horários ideais de consumo.'\n"
        "Este plano já está OTIMIZADO. Não proponhas mudanças.\n"
        "Escreve ~200 palavras em Português (PT-PT) a explicar a um utilizador doméstico **quando é melhor ligar cada aparelho**, "
        f"Deves manter o rigor técnico, mas introduzir o tom e maneirismos próprios da personagem {who}. "
        "Por exemplo, podes usar expressões típicas, formas de tratamento ou pequenas alusões ao universo da personagem. "
        "Mas nunca alteres os números, horários ou factos.\n\n"
        "com base nas janelas ótimas (15 minutos) fornecidas, e indica os números principais.\n\n"
        "Para cada aparelho, repete fielmente os factos da lista abaixo, incluindo a janela otimizada (formato HHhMM–HHhMM), "
        "e formula no estilo: 'A melhor hora para ligar o [aparelho] é ...'. "
        "Indica apenas a energia total por aparelho (energia_total_kWh). NÃO indiques energia por sessão.\n\n"
        "Factos por aparelho (repete fielmente):\n"
        + "\n".join(windows_lines) + "\n\n"
        f"Total de energia do dia (kWh): {total_kwh:.1f}\n"
        f"Pico de potência (kW): {peak_kw:.1f}" + (f" às {hhmm}\n" if hhmm else "\n") +
        (
            "\nCopia as linhas abaixo EXACTAMENTE numa secção final com o título 'Custos do dia':\n"
            + "\n".join(f"- {x}" for x in cost_lines) + "\n"
            if cost_lines else "\n(Não há dados de custos para este dia.)\n"
        ) +
        "\n24h CSV (Hour,Power_W):\n" + csv_24h
    )

    # ---- Generate report text ----
    text = generate_text(system, user, max_tokens=420)

    # ---- Post-process: garantir persona correta e custos presentes ----
    header_line = f"Olá! Sou {who},"
    if header_line not in text[:160]:
        # Prepend mandatory opening if model slipped
        text = f"{header_line} e estou aqui para indicar os horários ideais de consumo.\n\n{text}"

    if cost_lines and "Custos do dia" not in text:
        # Append costs section verbatim if missing
        text = text.rstrip() + "\n\n## Custos do dia\n" + "\n".join(f"- {x}" for x in cost_lines) + "\n"

    return Response(
        content=json.dumps({"persona": who, "text": text}, ensure_ascii=False),
        media_type="application/json",
    )

# =============== OpenAI TTS (MP3) ===============
OPENAI_TTS_MODEL = os.getenv("OPENAI_TTS_MODEL", "gpt-4o-mini-tts")
OPENAI_TTS_VOICE = os.getenv("OPENAI_TTS_VOICE", "alloy")

def openai_tts_pt_to_mp3(text: str) -> str:
    """Synthesize Portuguese text into a temp MP3 using OpenAI TTS."""
    client = OpenAI()
    fd, path = tempfile.mkstemp(suffix=".mp3"); os.close(fd)
    with client.audio.speech.with_streaming_response.create(
        model=OPENAI_TTS_MODEL,
        voice=OPENAI_TTS_VOICE,
        input=text,
    ) as resp:
        resp.stream_to_file(path)
    return path

# =============== Audio endpoint (speaks the same text) ===============
@app.post("/persona_report_audio")
def persona_report_audio(payload: OptimizationSchedule = Body(...), persona: Optional[str] = None):
    """
    1) Reuse /persona_report to get EXACT same persona + text.
    2) Strip Markdown, then synthesize MP3 using OpenAI TTS.
    """
    resp = persona_report(payload, persona)
    data = json.loads(resp.body.decode("utf-8"))
    raw_text = (data.get("text") or "").strip()
    text = strip_markdown(raw_text)
    if not text:
        return JSONResponse({"error": "empty text from persona_report"}, status_code=500)

    try:
        mp3_path = openai_tts_pt_to_mp3(text)
    except Exception as e:
        return JSONResponse({"error": f"TTS failed: {e}"}, status_code=500)

    task = BackgroundTask(lambda p=mp3_path: os.path.exists(p) and os.unlink(p))
    return FileResponse(mp3_path, media_type="audio/mpeg", filename="persona_report.mp3", background=task)
