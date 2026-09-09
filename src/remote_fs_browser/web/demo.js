import { RemoteFsClient } from '/browser.js'
const picker = document.querySelector('remote-fs-browser')
document.querySelector('#start').onclick = async () => {
  await picker.disconnect()
  const token = document.querySelector('#token').value
  picker.client = new RemoteFsClient(location.origin, () => ({ Authorization: `Bearer ${token}` }))
  void picker.discover()
}
picker.addEventListener('path-selected', event => { document.querySelector('#result').textContent = JSON.stringify(event.detail,null,2) })
