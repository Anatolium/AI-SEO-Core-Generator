document.addEventListener('DOMContentLoaded', function() {
    const form = document.getElementById('seo-form');
    const logDiv = document.getElementById('log');
    const resultDiv = document.getElementById('result');
    let currentTaskId = null;
    let pollTimer = null;
    const BACKEND = 'http://localhost:8000';

    form.addEventListener('submit', async function(e) {
        e.preventDefault();
        clearInterval(pollTimer);
        logDiv.textContent = 'Запуск анализа...';
        resultDiv.textContent = '';
        const url = document.getElementById('url').value;
        try {
            const resp = await fetch(`${BACKEND}/analyze`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ url })
            });
            const data = await resp.json();
            if (data.error) {
                logDiv.textContent = data.error;
                return;
            }
            currentTaskId = data.task_id;
            logDiv.textContent = 'Анализ запущен. Ожидайте...';
            pollLogAndResult();
            pollTimer = setInterval(pollLogAndResult, 2000);
        } catch (err) {
            logDiv.textContent = 'Ошибка соединения с backend.';
        }
    });

    async function pollLogAndResult() {
        if (!currentTaskId) return;
        try {
            const logResp = await fetch(`${BACKEND}/log/${currentTaskId}`);
            const logData = await logResp.json();
            if (logData.log) {
                logDiv.textContent = logData.log.join('\n');
            }
            if (logData.status === 'done' || logData.status === 'error') {
                clearInterval(pollTimer);
                const resResp = await fetch(`${BACKEND}/result/${currentTaskId}`);
                const resData = await resResp.json();
                if (resData.result) {
                    resultDiv.textContent = resData.result;
                } else if (logData.status === 'error') {
                    resultDiv.textContent = 'Произошла ошибка при генерации SEO-ядра.';
                }
            }
        } catch (err) {
            console.error(err);
        }
    }
}); 