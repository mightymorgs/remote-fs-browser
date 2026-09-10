import { RemoteFsClient } from '/browser.js'

const picker = document.querySelector('remote-fs-browser')
const app = document.querySelector('#app')
const signin = document.querySelector('#signin')
const status = document.querySelector('#login-status')
const toast = document.querySelector('#saved-toast')
const result = document.querySelector('#result')

const mode = new URLSearchParams(location.search).get('mode') === 'select' ? 'select' : 'browse'
picker.setAttribute('mode', mode)
picker.render()

document.querySelector('#origin').textContent = location.origin
document.querySelector('#transport').textContent = location.protocol === 'https:'
  ? '' : 'Plain HTTP — use a trusted network or a tunnel.'

const client = new RemoteFsClient(location.origin + '/api')
picker.client = client

picker.download = (id, item) => {
  const link = document.createElement('a')
  link.href = `${client.baseUrl}/sessions/${encodeURIComponent(id)}/file?${new URLSearchParams({ path: item.path })}`
  link.download = item.name
  document.body.append(link); link.click(); link.remove()
}

function setStatus(text, state) {
  status.textContent = text
  if (state) status.dataset.state = state; else delete status.dataset.state
}

async function enter(hostname) {
  document.querySelector('#signin-title').textContent = `Sign in to ${hostname}`
  signin.hidden = true
  app.dataset.ready = 'true'
  await picker.discover()
}

document.querySelector('#signin-form').onsubmit = async event => {
  event.preventDefault()
  const password = document.querySelector('#password')
  const username = document.querySelector('#username')
  setStatus('Signing in…')
  try {
    await picker.disconnect()
    const session = await client.request('/login', { method: 'POST', body: { username: username.value, password: password.value } })
    password.value = ''
    setStatus('Connected.')
    await enter(session.hostname)
  } catch (error) { setStatus(error.message, 'error') }
}

picker.addEventListener('sign-out', async () => {
  await picker.disconnect()
  await client.request('/login', { method: 'DELETE' }).catch(() => {})
  delete app.dataset.ready
  signin.hidden = false
  delete toast.dataset.open
  setStatus('Signed out.')
})

picker.addEventListener('path-selected', event => {
  result.textContent = JSON.stringify(event.detail, null, 2)
  toast.dataset.open = 'true'
})

document.querySelector('#copy').onclick = async () => {
  if (navigator.clipboard) await navigator.clipboard.writeText(result.textContent).catch(() => {})
}

// Resume the browser cookie after refreshing or switching modes.
client.request('/login')
  .then(session => enter(session.hostname))
  .catch(() => {})
