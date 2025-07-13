// main.js
const { app, BrowserWindow } = require('electron');
const { spawn } = require('child_process');
const path = require('path');
const os = require('os');

let flaskProcess = null;
const FLASK_PORT = 5000; // Choose a port for your Flask app

function createWindow() {
    const win = new BrowserWindow({
        width: 1200, // Adjusted width
        height: 800, // Adjusted height
        minWidth: 1000, // Minimum width
        minHeight: 700, // Minimum height
        icon: path.join(__dirname, 'icon.png'), // Optional: path to your app icon
        webPreferences: {
            nodeIntegration: false, // Keep false for security
            contextIsolation: true, // Keep true for security
            // preload: path.join(__dirname, 'preload.js') // If you need a preload script
        }
    });

    // Check if Flask is running, then load the URL
    const loadFlaskApp = () => {
        // In a packaged app, the Flask executable will be in a specific path
        // For development, it's just 'python app.py'
        const flaskAppPath = path.join(__dirname, 'app', 'app.py');
        let pythonExecutable;
        let scriptArgs = [flaskAppPath];

        if (app.isPackaged) {
            // For packaged app:
            // The Flask executable will be bundled by PyInstaller
            // and placed in a location accessible by Electron.
            // This path needs to be adjusted based on your PyInstaller output
            // and electron-builder configuration.
            // Example: If PyInstaller creates 'dist/app/app'
            // and electron-builder puts it in 'resources/app.asar.unpacked/python_dist'
            pythonExecutable = path.join(process.resourcesPath, 'app.asar.unpacked', 'python_dist', (os.platform() === 'win32' ? 'app.exe' : 'app'));
            
            // Pass the userData path to Flask for profiles.db and data
            scriptArgs = ['--user-data-path', app.getPath('userData')]; // We'll modify app.py to accept this
            
        } else {
            // For development: Assuming 'python' or 'python3' is in PATH
            pythonExecutable = process.platform === 'win32' ? 'python.exe' : 'python3';
        }

        console.log(`Attempting to launch Flask: ${pythonExecutable} ${scriptArgs.join(' ')}`);

        flaskProcess = spawn(pythonExecutable, scriptArgs, {
            cwd: app.isPackaged ? path.join(process.resourcesPath, 'app.asar.unpacked', 'python_dist') : path.join(__dirname, 'app'), // Set CWD for Flask
            env: { ...process.env, FLASK_APP_PORT: FLASK_PORT.toString(), FLASK_DEBUG: '0' } // Pass port via env var
        });

        flaskProcess.stdout.on('data', (data) => {
            console.log(`Flask stdout: ${data}`);
            // Wait for Flask to indicate it's ready, or just try to load after a delay
            if (data.includes(`Running on http://127.0.0.1:${FLASK_PORT}`)) {
                console.log('Flask app is running, loading window...');
                win.loadURL(`http://127.0.0.1:${FLASK_PORT}`);
            }
        });

        flaskProcess.stderr.on('data', (data) => {
            console.error(`Flask stderr: ${data}`);
        });

        flaskProcess.on('close', (code) => {
            console.log(`Flask process exited with code ${code}`);
            if (code !== 0 && code !== null) {
                // If Flask exits unexpectedly, you might want to show an error
                console.error('Flask app crashed!');
                // win.loadFile('error.html'); // Load an error page
            }
        });

        flaskProcess.on('error', (err) => {
            console.error('Failed to start Flask process:', err);
            // win.loadFile('error.html'); // Load an error page
        });
    };

    loadFlaskApp(); // Call the function to launch Flask and load the app

    // Open the DevTools.
    // win.webContents.openDevTools();
}

app.whenReady().then(createWindow);

// Quit when all windows are closed, except on macOS. There, it's common
// for applications and their menu bar to stay active until the user quits
// explicitly with Cmd + Q.
app.on('window-all-closed', () => {
    if (process.platform !== 'darwin') {
        app.quit();
    }
});

app.on('activate', () => {
    // On OS X it's common to re-create a window in the app when the
    // dock icon is clicked and there are no other windows open.
    if (BrowserWindow.getAllWindows().length === 0) {
        createWindow();
    }
});

app.on('will-quit', () => {
    // Kill the Flask process when the Electron app is about to quit
    if (flaskProcess) {
        console.log('Killing Flask process...');
        flaskProcess.kill();
        flaskProcess = null;
    }
});