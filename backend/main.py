# --- Вариант со скачиванием HTML сайта ---
import os
from openai import AsyncOpenAI
import httpx
import asyncio
import uuid
from fastapi import FastAPI, Request, BackgroundTasks
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

RESULTS_DIR = "results"
os.makedirs(RESULTS_DIR, exist_ok=True)

load_dotenv()

# --- Конфигурация OpenAI ---
PROXYAPI_KEY = os.getenv("PROXYAPI_KEY")
if not PROXYAPI_KEY:
    raise ValueError("PROXYAPI_KEY не найден в переменных окружения")

BASE_URL = os.getenv("OPENAI_BASE_URL")
if not BASE_URL:
    raise ValueError("BASE_URL не найден в переменных окружения")

openai_client = AsyncOpenAI(
    api_key=PROXYAPI_KEY,
    base_url=BASE_URL
)

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Хранилище логов и результатов (in-memory)
TASKS = {}

# Системный промпт для генерации плана
SYSTEM_PROMPT = (
    "Составь пошаговый план (5-6 шагов) для анализа сайта по ссылке и генерации SEO-ядра. "
    "Верни результат в JSON, каждый шаг — отдельный промпт."
)


def extract_domain(url: str):
    url = url.replace("https://", "").replace("http://", "").split("/")[0]
    return url.replace("www.", "")


async def fetch_html(url):
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            return resp.text
    except Exception as e:
        return f"[Ошибка загрузки HTML: {e}]"


async def chatgpt_call(messages, model="gpt-3.5-turbo"):
    resp = await openai_client.chat.completions.create(
        model=model,
        messages=messages,
        temperature=0.2,
        max_tokens=1200
    )
    return resp.choices[0].message.content


async def analyze_task(task_id, url):
    TASKS[task_id] = {"log": [], "result": None, "status": "running"}
    log = TASKS[task_id]["log"]

    try:
        # Получение плана
        log.append("[1/6] Запрашиваю план анализа у ChatGPT...")
        plan_json = await chatgpt_call([
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": url}
        ])

        import json
        try:
            plan = json.loads(plan_json)
        except Exception:
            log.append("Ошибка: ChatGPT вернул некорректный JSON.\n" + plan_json)
            TASKS[task_id]["status"] = "error"
            return

        steps = plan if isinstance(plan, list) else plan.get("steps") or list(plan.values())
        if not steps or not isinstance(steps, list):
            log.append("Ошибка: Не удалось извлечь шаги из плана.")
            TASKS[task_id]["status"] = "error"
            return

        log.append(f"План анализа получен. Шагов: {len(steps)}")

        # Выполнение шагов
        step_results = []
        for idx, step in enumerate(steps, 1):
            log.append(f"[Шаг {idx}] {step}")

            try:
                answer = await chatgpt_call([
                    {"role": "system", "content": step},
                    {"role": "user", "content": url}
                ])

                # Если модель говорит что не видит сайт → подгружаем HTML
                if "не могу" in answer.lower() or "нет доступа" in answer.lower():
                    html = await fetch_html(url)
                    answer = await chatgpt_call([
                        {"role": "system", "content": step},
                        {"role": "user", "content": html}
                    ])

                log.append(f"Ответ: {answer}\n")
                step_results.append({"step": step, "result": answer})

            except Exception as e:
                log.append(f"Ошибка на шаге {idx}: {e}")
                step_results.append({"step": step, "result": f"Ошибка: {e}"})

        # Окончательный анализ
        log.append("[Финал] Собираю SEO-ядро...")

        summary_prompt = (
            "На основе всех промежуточных результатов шагов анализа сайта, собери финальное SEO-ядро. "
            "Верни итоговое SEO-ядро строго в структурированном JSON виде."
        )

        summary_input = "\n\n".join(
            [f"Шаг: {s['step']}\nРезультат: {s['result']}" for s in step_results]
        )

        final_result = await chatgpt_call([
            {"role": "system", "content": summary_prompt},
            {"role": "user", "content": summary_input}
        ])

        # --- Сохранение в JSON-файл ---
        domain_name = extract_domain(url)
        filename = os.path.join(RESULTS_DIR, f"seo_core_{domain_name}_{task_id[:8]}.json")

        try:
            json_data = json.loads(final_result)  # проверяем что JSON валидный

            with open(filename, "w", encoding="utf-8") as f:
                json.dump(json_data, f, ensure_ascii=False, indent=2)

            log.append(f"SEO-ядро сохранено в файл: {filename}")

            TASKS[task_id]["result"] = (
                f'SEO-ядро успешно сгенерировано и сохранено в файл: {filename}'
            )
            TASKS[task_id]["status"] = "done"

        except Exception as e:
            log.append(f"Ошибка при сохранении SEO-ядра: {e}")
            TASKS[task_id]["result"] = final_result
            TASKS[task_id]["status"] = "error"

    except Exception as e:
        log.append(f"Критическая ошибка: {e}")
        TASKS[task_id]["status"] = "error"


@app.post("/analyze")
async def analyze(request: Request, background_tasks: BackgroundTasks):
    data = await request.json()
    url = data.get("url")
    if not url:
        return JSONResponse({"error": "URL не передан"}, status_code=400)
    task_id = str(uuid.uuid4())
    background_tasks.add_task(analyze_task, task_id, url)
    return JSONResponse({"task_id": task_id})


@app.get("/log/{task_id}")
async def get_log(task_id: str):
    task = TASKS.get(task_id)
    if not task:
        return JSONResponse({"error": "Нет такого задания"}, status_code=404)
    return JSONResponse({"log": task["log"], "status": task["status"]})


@app.get("/result/{task_id}")
async def get_result(task_id: str):
    task = TASKS.get(task_id)
    if not task:
        return JSONResponse({"error": "Нет такого задания"}, status_code=404)
    return JSONResponse({"result": task["result"], "status": task["status"]})


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)
