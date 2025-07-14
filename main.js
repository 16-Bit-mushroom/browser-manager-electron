// main.js
const { app, BrowserWindow } = require('electron');
const { spawn } = require('child_process');
const path = require('path');
const fs = require('fs');

let flaskProcess = null;
let mainWindow = null;
const FLASK_PORT = 5000;
let flaskReady = false; // New flag to track Flask readiness state

function createWindow() {
    mainWindow = new BrowserWindow({
        width: 1000,
        height: 700,
        webPreferences: {
            nodeIntegration: false,
            contextIsolation: true,
            sandbox: true
        }
    });

    //mainWindow.webContents.openDevTools(); // Keep DevTools open for debugging

    function createFlaskProcess() {
        let flaskExecutablePath;
        if (app.isPackaged) {
            flaskExecutablePath = path.join(process.resourcesPath, 'app-backend', 'browser_manager_flask_app.exe');
        } else {
            flaskExecutablePath = path.join(__dirname, 'app', 'dist', 'browser_manager_flask_app', 'browser_manager_flask_app.exe');
        }

        console.log('Attempting to start Flask backend at:', flaskExecutablePath);

        if (!fs.existsSync(flaskExecutablePath)) {
            console.error('Flask executable not found at:', flaskExecutablePath);
            if (mainWindow) {
                mainWindow.loadURL(`data:text/html,<h1>Error</h1><p>Flask backend not found!</p><p>Expected at: ${flaskExecutablePath}</p>`);
            }
            return;
        }

        const userDataPath = app.getPath('userData');
        if (!fs.existsSync(userDataPath)) {
            try {
                fs.mkdirSync(userDataPath, { recursive: true });
                console.log('Created user data path:', userDataPath);
            } catch (err) {
                console.error('Failed to create user data path:', err);
                if (mainWindow) {
                    mainWindow.loadURL(`data:text/html,<h1>Error</h1><p>Failed to create user data directory.</p><p>Error: ${err.message}</p>`);
                }
                return;
            }
        }

        
        flaskProcess = spawn(flaskExecutablePath, ['--user-data-path', userDataPath]);

        // Function to check if Flask is ready from any output stream
        const checkFlaskReady = (output) => {
            if (!flaskReady && output.includes(`Running on http://127.0.0.1:${FLASK_PORT}`)) {
                console.log('Flask backend is ready. Loading URL...');
                flaskReady = true; // Set flag to true
                // Give Flask a moment to fully bind to the port
                setTimeout(() => {
                    if (mainWindow && !mainWindow.isDestroyed()) { // Check if window still exists
                        mainWindow.loadURL(`http://127.0.0.1:${FLASK_PORT}`);
                    }
                }, 1000);
            }
        };

        // Listen for stdout
        flaskProcess.stdout.on('data', (data) => {
            const output = data.toString();
            console.log('Flask stdout:', output);
            checkFlaskReady(output); // Check for "Running on..." from stdout
        });

        // Listen for stderr
        flaskProcess.stderr.on('data', (data) => {
            const errorOutput = data.toString();
            console.error('Flask stderr:', errorOutput);
            checkFlaskReady(errorOutput); // Check for "Running on..." from stderr (as it appears in your case)

            // IMPORTANT: Only show the error page if Flask is NOT ready AND
            // the stderr output doesn't contain the "Running on" message (which means it's a true error)
            if (!flaskReady && !errorOutput.includes(`Running on http://127.0.0.1:${FLASK_PORT}`)) {
                if (mainWindow && !mainWindow.webContents.getURL().includes('data:')) {
                    mainWindow.loadURL(`data:text/html,<h1>Flask Error</h1><p>Check console for details.</p><p>Error: ${errorOutput.substring(0, 500)}...</p>`);
                }
            }
        });

        flaskProcess.on('close', (code) => {
            console.log('Flask process exited with code', code);
            // Only show server offline if it was previously ready or if it crashed before starting properly
            if (mainWindow && (flaskReady || code !== 0)) { // If it was ready and closed, or crashed with non-zero code
                mainWindow.loadURL('data:text/html,<h1>Server Offline</h1><p>The Flask backend has closed unexpectedly. Code: ' + code + '</p>');
            }
        });

        flaskProcess.on('error', (err) => {
            console.error('Failed to spawn Flask process:', err);
            if (mainWindow) {
                mainWindow.loadURL(`data:text/html,<h1>Launch Error</h1><p>Could not launch Flask backend.</p><p>Error: ${err.message}</p>`);
            }
        });
    }

    createFlaskProcess();

    mainWindow.on('closed', () => {
        mainWindow = null;
        if (flaskProcess) {
            console.log('Killing Flask process...');
            flaskProcess.kill();
            flaskProcess = null;
        }
    });
}

app.whenReady().then(createWindow);

app.on('window-all-closed', () => {
    if (process.platform !== 'darwin') {
        app.quit();
    }
});

app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) {
        createWindow();
    }
});