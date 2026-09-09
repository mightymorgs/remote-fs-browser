import { RemoteFsClient } from '/browser.js'
const picker = document.querySelector('remote-fs-browser')
const mode = new URLSearchParams(location.search).get('mode') === 'select' ? 'select' : 'browse'
picker.setAttribute('mode', mode)
picker.render()
document.querySelector('#selection').hidden = mode !== 'select'
const client = new RemoteFsClient(location.origin + '/api')
picker.client = client
picker.download = (id, item) => {
  const link = document.createElement('a')
  link.href = `${client.baseUrl}/sessions/${encodeURIComponent(id)}/file?${new URLSearchParams({path:item.path})}`
  link.download = item.name
  document.body.append(link); link.click(); link.remove()
}
document.querySelector('#start').onclick = async () => {
  const status = document.querySelector('#login-status')
  try {
    await picker.disconnect()
    const token = document.querySelector('#token')
    const login = new RemoteFsClient(location.origin + '/api', () => ({Authorization:`Bearer ${token.value}`}))
    const result = await login.request('/login', {method:'POST'})
    token.value = ''
    document.querySelector('h1').textContent = `Storage visible to ${result.hostname}`
    status.textContent = 'Connected. Access expires after eight hours.'
    await picker.discover()
  } catch (error) { status.textContent = error.message }
}
document.querySelector('#logout').onclick = async () => {
  await picker.disconnect()
  await client.request('/login', {method:'DELETE'}).catch(() => {})
  document.querySelector('#login-status').textContent = 'Signed out.'
}
picker.addEventListener('path-selected', event => {
  document.querySelector('#result').value = JSON.stringify(event.detail,null,2)
})
document.querySelector('#copy').onclick = async () => {
  const result = document.querySelector('#result')
  result.focus(); result.select()
  if (navigator.clipboard) await navigator.clipboard.writeText(result.value)
  else document.execCommand('copy')
}

// Resume the browser cookie after refreshing or switching modes.
client.request('/login').then(async result => {
  document.querySelector('h1').textContent = `Storage visible to ${result.hostname}`
  document.querySelector('#login-status').textContent = 'Connected.'
  await picker.discover()
}).catch(() => {})
