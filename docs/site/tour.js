const tabs = [...document.querySelectorAll('[role="tab"]')];
const panels = [...document.querySelectorAll('[role="tabpanel"]')];
const play = document.querySelector('#play-tour');
const previous = document.querySelector('#tour-prev');
const next = document.querySelector('#tour-next');
let current = 0;
let timer;
function stop() {
  clearInterval(timer);
  timer = undefined;
  play.textContent = 'Play tour';
  play.setAttribute('aria-pressed', 'false');
}
function show(index, focus = false) {
  current = (index + tabs.length) % tabs.length;
  tabs.forEach((tab, i) => {
    tab.setAttribute('aria-selected', String(i === current));
    tab.tabIndex = i === current ? 0 : -1;
    panels[i].hidden = i !== current;
  });
  document.querySelector('#tour-position').textContent = `Chapter ${current + 1} of ${tabs.length}`;
  if (focus) tabs[current].focus();
}
if (tabs.length) {
  [play, previous, next].forEach(button => { button.hidden = false; });
  tabs.forEach((tab, index) => {
    tab.addEventListener('click', () => { stop(); show(index); });
    tab.addEventListener('keydown', event => {
      const target = {ArrowRight: current + 1, ArrowLeft: current - 1, Home: 0, End: tabs.length - 1}[event.key];
      if (target !== undefined) { event.preventDefault(); stop(); show(target, true); }
    });
  });
  previous.addEventListener('click', () => { stop(); show(current - 1); });
  next.addEventListener('click', () => { stop(); show(current + 1); });
  play.addEventListener('click', () => {
    if (timer) return stop();
    if (current === tabs.length - 1) show(0);
    play.textContent = 'Pause tour';
    play.setAttribute('aria-pressed', 'true');
    timer = setInterval(() => {
      if (current === tabs.length - 1) return stop();
      show(current + 1);
    }, 10000);
  });
  document.addEventListener('visibilitychange', () => { if (document.hidden) stop(); });
  document.querySelector('#tour').addEventListener('focusin', event => {
    if (event.target !== play) stop();
  });
  stop();
}
const video = document.querySelector('#product-video');
document.querySelectorAll('[data-seek]').forEach(button => button.addEventListener('click', () => {
  stop();
  video.currentTime = Number(button.dataset.seek);
  video.play().catch(() => { video.focus(); });
}));
