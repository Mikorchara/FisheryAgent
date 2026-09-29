// Manual, offline browser check. Requires a local web server and headless Edge CDP.
const {setTimeout: delay} = require('node:timers/promises');

async function main() {
  const targets = await fetch('http://127.0.0.1:9333/json/list').then((r) => r.json());
  const target = targets.find((item) => item.type === 'page');
  if (!target) throw Error('NO_BROWSER_PAGE');
  const socket = new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((resolve, reject) => {
    socket.addEventListener('open', resolve, {once: true});
    socket.addEventListener('error', reject, {once: true});
  });
  let nextId = 0;
  const pending = new Map();
  socket.addEventListener('message', (event) => {
    const message = JSON.parse(event.data);
    if (!message.id || !pending.has(message.id)) return;
    const {resolve, reject} = pending.get(message.id);
    pending.delete(message.id);
    if (message.error) reject(Error(message.error.message));
    else resolve(message.result);
  });
  const send = (method, params = {}) => new Promise((resolve, reject) => {
    const id = ++nextId;
    pending.set(id, {resolve, reject});
    socket.send(JSON.stringify({id, method, params}));
  });
  const evaluate = async (expression) => {
    const reply = await send('Runtime.evaluate', {expression, returnByValue: true,
      awaitPromise: true});
    if (reply.exceptionDetails) throw Error('BROWSER_SCRIPT_ERROR');
    return reply.result.value;
  };
  try {
    await send('Page.enable');
    await send('Runtime.enable');
    await send('Page.navigate', {url: 'http://127.0.0.1:8877/'});
    let ready = false;
    for (let count = 0; count < 100; count++) {
      try {
        ready = await evaluate("document.querySelector('#profile')?.options.length > 0");
      } catch (_) {}
      if (ready) break;
      await delay(100);
    }
    if (!ready) throw Error('PAGE_NOT_READY');
    await evaluate("document.querySelector('#response-mode').value='streaming'; document.querySelector('#analyze').click(); true");
    let status = '';
    for (let count = 0; count < 100; count++) {
      status = await evaluate("document.querySelector('#status').textContent");
      if (status.includes('完成') || status.includes('失败') || status.includes('ERROR')) break;
      await delay(100);
    }
    const outputLength = await evaluate("document.querySelector('#streaming-output').textContent.length");
    const factsCount = await evaluate("document.querySelectorAll('#facts dt').length");
    console.log('STATUS', status);
    console.log('OUTPUT_LENGTH', outputLength);
    console.log('FACTS_COUNT', factsCount);
    if (status !== '流式分析完成。' || outputLength === 0 || factsCount === 0) {
      const missing = await evaluate("['facts','rules','evidence','structured','recommendations','uncertainty','runtime','model-output','streaming-output','results','empty-state','model-inference'].filter(id=>!document.getElementById(id))");
      console.log('MISSING_IDS', missing);
      const diagnostic = await evaluate("(async()=>{try{await analyzeStreaming({profile_id:'mock-demo',scenario:'low_oxygen',question:'当前水质情况怎么样？',confirm_network:false});return 'NO_THROW'}catch(error){return error.name+': '+error.message+' @ '+error.stack?.split('\\n').slice(0,3).join(' | ')}})()");
      console.log('CLIENT_DIAGNOSTIC', diagnostic);
      process.exitCode = 1;
    }
  } finally {
    await send('Browser.close').catch(() => {});
    socket.close();
  }
}

main().catch((error) => {
  console.log('BROWSER_PROBE_ERROR', error.message);
  process.exitCode = 1;
});
