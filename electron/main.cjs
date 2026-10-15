const { app, BrowserWindow, shell } = require("electron");
const path = require("node:path");
const { pathToFileURL } = require("node:url");
function createWindow() {
  const win = new BrowserWindow({ width: 1360, height: 850, minWidth: 1000, minHeight: 650, backgroundColor: "#f7f8fa", webPreferences: { contextIsolation: true, nodeIntegration: false, sandbox: true } });
  const devUrl = process.env.FACTORYPULSE_DEV_URL || (app.isPackaged ? null : "http://127.0.0.1:5173");
  if (devUrl) win.loadURL(devUrl);
  else win.loadURL(pathToFileURL(path.join(__dirname, "../dist/index.html")).href);
  win.webContents.setWindowOpenHandler(({ url }) => { if (url.startsWith("https://")) shell.openExternal(url); return { action: "deny" }; });
}
app.whenReady().then(() => { createWindow(); app.on("activate", () => { if (BrowserWindow.getAllWindows().length === 0) createWindow(); }); });
app.on("window-all-closed", () => { if (process.platform !== "darwin") app.quit(); });
