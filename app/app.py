import os
import sqlite3
from flask import Flask, render_template, request, redirect, url_for, g, jsonify, session, send_file
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from functools import wraps
import datetime
import subprocess
import shutil
import sys
import argparse
import platform
import webbrowser
import zipfile
import requests
import hashlib
import json
import zipfile
import tempfile
import tarfile
import bz2

# --- Add Argument Parsing ---
parser = argparse.ArgumentParser(description='Flask Backend for Browser Manager.')
parser.add_argument('--user-data-path', type=str, help='Path to store user data (profiles, database).')
args = parser.parse_args()
# --- End Argument Parsing ---

app = Flask(__name__)
app.secret_key = 'super-secret-123'

def login_required_page(view_func):
    @wraps(view_func)
    def wrapper(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('index'))  # redirect to login
        return view_func(*args, **kwargs)
    return wrapper

# --- MODIFIED PATH CONFIGURATION for different data types ---
def get_application_paths():
    """
    Determines base paths for:
    1. Mutable user data (database, generated profiles) - goes into Electron's userData path.
    2. Read-only application resources (like pre-bundled browser binaries) - copied by Electron Builder.
    """
    mutable_user_data_base_path = None
    read_only_resources_base_path = None
    

    if getattr(sys, 'frozen', False):
        # The application is frozen (running as an executable)
        # Mutable User Data Path: Passed from Electron's userData directory
        if args.user_data_path:
            mutable_user_data_base_path = os.path.join(args.user_data_path, 'BrowserManagerData')
        else:
            # Fallback if --user-data-path not provided (should not happen with Electron)
            mutable_user_data_base_path = os.path.join(os.path.dirname(sys.executable), 'data_fallback') # Just a fallback

        # Read-only Resources Path: Copied by Electron-Builder to [app_root]/data/
        # Flask executable is at [app_root]/resources/app-backend/browser_manager_flask_app.exe
        # So, relative path from Flask exe to 'data' folder: ../../data/
        flask_exe_dir = os.path.dirname(sys.executable)
        app_root_dir = os.path.join(flask_exe_dir, '..', '..') # Go up from resources/app-backend to app_root
        read_only_resources_base_path = os.path.join(app_root_dir, 'data') # Points to [app_root]/data
    else:
        # The application is not frozen (running as a regular Python script - development mode)
        current_script_dir = os.path.abspath(os.path.dirname(__file__))
        mutable_user_data_base_path = os.path.join(current_script_dir, 'data', 'user_data_dev') # Separate data for dev
        read_only_resources_base_path = os.path.join(current_script_dir, 'data') # Browser binaries from dev 'data' folder

    return mutable_user_data_base_path, read_only_resources_base_path

# Get the determined paths
MUTABLE_USER_DATA_PATH, READ_ONLY_RESOURCES_PATH = get_application_paths()

# Configure Flask app with these paths
app.config['DATABASE'] = os.path.join(MUTABLE_USER_DATA_PATH, 'profiles.db')
# app.config['BROWSER_BINARIES_DIR'] = os.path.join(READ_ONLY_RESOURCES_PATH, 'browser_binaries') # This is the key change!
app.config['BROWSER_BINARIES_DIR'] = os.path.join(
    os.path.dirname(__file__), "data", "browser_binaries"
)
os.makedirs(app.config['BROWSER_BINARIES_DIR'], exist_ok=True)

app.config['PROFILES_DIR'] = os.path.join(MUTABLE_USER_DATA_PATH, 'profiles')

# Ensure only the MUTABLE directories exist.
# Electron Builder handles copying the read-only 'browser_binaries' directory.
os.makedirs(MUTABLE_USER_DATA_PATH, exist_ok=True)
os.makedirs(app.config['PROFILES_DIR'], exist_ok=True)
BROWSER_MANIFEST = os.path.join(os.path.dirname(__file__), 'browsers.json')

#
def get_db():
    """Connects to the specific database."""
    db = getattr(g, '_database', None)
    if db is None:
        db = g._database = sqlite3.connect(app.config['DATABASE'])
        db.row_factory = sqlite3.Row  # This makes rows behave like dicts
    return db

@app.teardown_appcontext
def close_connection(exception):
    """Closes the database again at the end of the request."""
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()

def init_db():
    """Initializes the database schema."""
    with app.app_context():
        db = get_db()
        cursor = db.cursor()
        # Create projects table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS projects (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                notes TEXT,
                last_used TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                is_deleted INTEGER DEFAULT 0,
                deleted_at TEXT
            )
        ''')
        # Create profiles table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS profiles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                browser TEXT NOT NULL,
                folder TEXT, -- This will store the relative path to the profile folder
                notes TEXT,
                proxy TEXT,
                save_cookies BOOLEAN DEFAULT 1,
                clear_session_on_exit BOOLEAN DEFAULT 0,
                last_used TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                project_id INTEGER,
                is_deleted INTEGER DEFAULT 0,
                deleted_at TEXT,
                FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE SET NULL
            )
        ''')

        db.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL
        )
    ''')

        
        db.commit()
        print("Database initialized.")


def create_default_admin():
    db = get_db()
    cursor = db.execute('SELECT * FROM users WHERE username = ?', ('admin',))
    if cursor.fetchone() is None:
        password_hash = generate_password_hash('admin123')
        db.execute('INSERT INTO users (username, password_hash) VALUES (?, ?)', 
                   ('admin', password_hash))
        db.commit()
        print("Default admin created: admin / admin123")
    else:
        print("Default admin already exists.")


# Call init_db when the application starts
with app.app_context():
    init_db()
    create_default_admin()

# --- Routes for serving HTML pages ---
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/new-project.html')
@login_required_page

def new_project_page():
    return render_template('new-project.html')

@app.route('/new-profile.html')
@login_required_page

def new_profile_page():
    return render_template('new-profile.html')

@app.route('/edit-profile.html')
@login_required_page

def edit_profile_page():
    return render_template('edit-profile.html')

@app.route('/edit-project.html')
@login_required_page

def edit_project_page():
    return render_template('edit-project.html')

@app.route('/projects.html')
@login_required_page

def projects_page():
    db = get_db()
    # Join with profiles table to count profiles per project for display
    # This is an example, actual display on projects.html might be different
    projects = db.execute('''
        SELECT p.id, p.name, p.notes, p.last_used, COUNT(prof.id) AS profile_count
        FROM projects p
        LEFT JOIN profiles prof ON p.id = prof.project_id
        GROUP BY p.id
        ORDER BY p.last_used DESC
    ''').fetchall()
    return render_template('projects.html', projects=projects)

@app.route('/profiles.html')
@login_required_page

def profiles_page():
    db = get_db()
    # Join with projects table to show project name instead of just ID
    profiles = db.execute('''
        SELECT prof.*, proj.name AS project_name
        FROM profiles prof
        LEFT JOIN projects proj ON prof.project_id = proj.id
        ORDER BY prof.last_used DESC
    ''').fetchall()
    return render_template('profiles.html', profiles=profiles)


@app.route('/browsers.html')
@login_required_page

def browsers_page():
    return render_template('browsers.html')


@app.route('/recycle-bin.html')
@login_required_page

def recycle_bin_page():
    return render_template('recycle-bin.html')


@app.route('/settings.html')
@login_required_page

def settings_page():
    return render_template('settings.html')

@app.route('/logout')
def logout():
    session.clear()  # Wipe all session data
    return redirect(url_for('index'))


# --- API Endpoints ---

@app.route('/api/current_user')
def current_user():
    db = get_db()
    user = db.execute('SELECT username FROM users WHERE id = 1').fetchone()
    return jsonify({'username': user['username']}), 200


@app.route('/api/update_user', methods=['POST'])
def update_user():
    db = get_db()
    data = request.json
    new_username = data.get('username')
    new_password = data.get('password')

    if not new_username:
        return jsonify({'error': 'Username is required'}), 400

    # Optional: prevent duplicate usernames
    existing = db.execute('SELECT id FROM users WHERE username = ? AND id != 1', (new_username,)).fetchone()
    if existing:
        return jsonify({'error': 'Username already taken'}), 409

    if new_password:
        hashed_password = generate_password_hash(new_password)
        db.execute('UPDATE users SET username = ?, password_hash = ? WHERE id = 1', (new_username, hashed_password))
    else:
        db.execute('UPDATE users SET username = ? WHERE id = 1', (new_username,))
    
    db.commit()
    return jsonify({'message': 'User credentials updated successfully'}), 200


@app.route('/login', methods=['POST'])
def login():
    if not request.is_json:
        return jsonify({"error": "Request must be JSON"}), 400

    data = request.get_json()
    username = data.get('username')
    password = data.get('password')

    if not username or not password:
        return jsonify({"error": "Username and password required."}), 400

    db = get_db()
    user = db.execute('SELECT * FROM users WHERE username = ?', (username,)).fetchone()

    if user and check_password_hash(user['password_hash'], password):
        session['user_id'] = user['id']
        session['username'] = user['username']
        return jsonify({"message": "Login successful"}), 200
    else:
        return jsonify({"error": "Invalid username or password"}), 401


@app.route('/api/create_project', methods=['POST'])
def create_project():
    if not request.is_json:
        return jsonify({"error": "Request must be JSON"}), 400

    data = request.get_json()
    name = data.get('name')
    notes = data.get('notes')

    if not name:
        return jsonify({"error": "Project name is required"}), 400

    db = get_db()
    try:
        cursor = db.cursor()
        cursor.execute('INSERT INTO projects (name, notes) VALUES (?, ?)', (name, notes))
        db.commit()
        return jsonify({"message": "Project created successfully!"}), 201
    except sqlite3.IntegrityError:
        return jsonify({"error": "Project with this name already exists."}), 409
    except Exception as e:
        db.rollback()
        return jsonify({"error": str(e)}), 500
    pass

@app.route('/api/projects', methods=['GET'])
def get_projects():
    """API endpoint to get a list of all projects with profile counts."""
    db = get_db()
    # Modified query to include profile_count and use GROUP BY
    projects = db.execute('''SELECT p.id, p.name, p.notes, p.last_used, COUNT(prof.id) AS profile_count
                          FROM projects p
                          LEFT JOIN profiles prof 
                          ON p.id = prof.project_id AND prof.is_deleted = 0
                          WHERE p.is_deleted = 0
                          GROUP BY p.id
                          ORDER BY p.name ASC
                          ''').fetchall()
    projects_list = []
    for row in projects:
        project_dict = dict(row)
        if project_dict['last_used']:
            dt_object = datetime.datetime.strptime(project_dict['last_used'], '%Y-%m-%d %H:%M:%S')
            project_dict['last_used_formatted'] = dt_object.strftime('%B %d, %Y %I:%M %p')
        else:
            project_dict['last_used_formatted'] = 'Never'
        projects_list.append(project_dict)
    return jsonify(projects_list), 200

@app.route('/api/projects/<int:project_id>', methods=['GET'])
def get_project_by_id(project_id):
    db = get_db()
    try:
        cursor = db.cursor()
        cursor.execute('SELECT id, name, notes, last_used FROM projects WHERE id = ?', (project_id,))
        project = cursor.fetchone()

        if not project:
            return jsonify({"error": "Project not found"}), 404

        project_dict = dict(project)

        if project_dict['last_used']:
            dt_object = datetime.datetime.strptime(project_dict['last_used'], '%Y-%m-%d %H:%M:%S')
            project_dict['last_used_formatted'] = dt_object.strftime('%B %d, %Y %I:%M %p')
        else:
            project_dict['last_used_formatted'] = 'Never'

        return jsonify(project_dict), 200
    except Exception as e:
        app.logger.error(f"Error fetching project by ID: {e}", exc_info=True)
        return jsonify({"error": "Failed to retrieve project"}), 500


@app.route('/api/projects/<int:project_id>', methods=['PUT'])
def edit_project(project_id):
    if not request.is_json:
        return jsonify({"error": "Request must be JSON"}), 400

    data = request.get_json()
    name = data.get('name')
    notes = data.get('notes')

    if not name:
        return jsonify({"error": "Project name is required"}), 400

    db = get_db()
    try:
        cursor = db.cursor()

        # Check if the project exists
        cursor.execute('SELECT * FROM projects WHERE id = ?', (project_id,))
        existing = cursor.fetchone()
        if not existing:
            return jsonify({"error": "Project not found"}), 404

        # Update the project
        cursor.execute('''
            UPDATE projects
            SET name = ?, notes = ?
            WHERE id = ?
        ''', (name, notes, project_id))
        db.commit()

        return jsonify({"message": "Project updated successfully!"}), 200
    except sqlite3.IntegrityError:
        return jsonify({"error": "A project with this name already exists."}), 409
    except Exception as e:
        db.rollback()
        app.logger.error(f"Error updating project: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500




@app.route('/api/create_profile', methods=['POST'])
def create_profile():
    if not request.is_json:
        return jsonify({"error": "Request must be JSON"}), 400

    data = request.get_json()
    name = data.get('name')
    browser_type_raw = data.get('browser') # e.g., 'Chrome', 'Firefox', 'Brave'
    notes = data.get('notes')
    proxy = data.get('proxy')
    save_cookies = data.get('save_cookies') 
    clear_session_on_exit = data.get('clear_session_on_exit') 
    project_id = data.get('project_id') 

    # Basic server-side validation
    if not name or not browser_type_raw:
        return jsonify({"error": "Profile Name and Browser are required!"}), 400

    if project_id is not None:
        try:
            project_id = int(project_id)
        except ValueError:
            return jsonify({"error": "Invalid project ID."}), 400
    
    # --- MODIFIED PATH CREATION LOGIC ---
    # Map browser type to its specific portable folder name
    browser_folder_map = {
        'chrome': 'GoogleChromePortable',
        'firefox': 'FirefoxPortable',
        'brave': 'BravePortable'
    }
    browser_dir_name = browser_folder_map.get(browser_type_raw)

    if not browser_dir_name:
        return jsonify({"error": f"Unsupported browser type: {browser_type_raw}"}), 400

    # Sanitize profile name for use in a file path
    safe_profile_name = "".join(c for c in name if c.isalnum() or c in (' ', '.', '_')).replace(' ', '_')
    
    # Construct the full unique absolute path for this profile's data directory
    # This path is relative to your project's 'data/profiles' directory
    profile_folder_path = os.path.join(app.config['PROFILES_DIR'], browser_dir_name, safe_profile_name)

    app.logger.info(f"DEBUG: profile_folder_path BEFORE DB INSERT: {profile_folder_path}") # Your debug line (keep for testing)

    db = get_db()
    try:
        # Create the profile directory (and parent directories if they don't exist)
        # This is where the browser will store its profile data
        os.makedirs(profile_folder_path, exist_ok=True)
        app.logger.info(f"Created profile directory: {profile_folder_path}")

        cursor = db.cursor()
        
        # Insert new profile into the database with the FULL ABSOLUTE PATH
        cursor.execute('''
            INSERT INTO profiles (name, browser, folder, notes, proxy, save_cookies, clear_session_on_exit, last_used, project_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (name, browser_type_raw, profile_folder_path, notes, proxy, save_cookies, clear_session_on_exit, datetime.datetime.now(), project_id))
        
        db.commit()
        return jsonify({"message": "Profile created successfully!"}), 201
    except sqlite3.IntegrityError:
        # Attempt to delete the created directory if DB insertion fails due to integrity error
        if os.path.exists(profile_folder_path) and os.path.isdir(profile_folder_path):
            try:
                os.rmdir(profile_folder_path) # Only removes empty directory
                app.logger.warning(f"Cleaned up empty profile directory after IntegrityError: {profile_folder_path}")
            except OSError as e:
                app.logger.error(f"Could not remove profile directory {profile_folder_path} after IntegrityError: {e}")
        return jsonify({"error": "Profile with this name already exists."}), 409
    except Exception as e:
        db.rollback()
        app.logger.error(f"Error creating profile: {e}", exc_info=True) # Log full traceback
        return jsonify({"error": str(e)}), 500

@app.route('/api/profiles', methods=['GET'])
def get_profiles():
    """API endpoint to get a list of all profiles."""
    db = get_db()
    profiles = db.execute('''
        SELECT prof.*, proj.name AS project_name
        FROM profiles prof
        LEFT JOIN projects proj ON prof.project_id = proj.id
        WHERE prof.is_deleted = 0
        ORDER BY prof.last_used DESC
    ''').fetchall()
    profiles_list = []
    for row in profiles:
        profile_dict = dict(row)
        if profile_dict['last_used']:
            try:
                # Try parsing with microseconds first (for newer entries)
                dt_object = datetime.datetime.strptime(profile_dict['last_used'], '%Y-%m-%d %H:%M:%S.%f')
            except ValueError:
                # If that fails, try parsing without microseconds (for older entries)
                dt_object = datetime.datetime.strptime(profile_dict['last_used'], '%Y-%m-%d %H:%M:%S')
            profile_dict['last_used_formatted'] = dt_object.strftime('%B %d, %Y %I:%M %p')
        else:
            profile_dict['last_used_formatted'] = 'Never'
        profile_dict['save_cookies_display'] = 'Yes' if profile_dict['save_cookies'] else 'No'
        profile_dict['clear_session_on_exit_display'] = 'Yes' if profile_dict['clear_session_on_exit'] else 'No'

        profiles_list.append(profile_dict)

    return jsonify(profiles_list), 200

@app.route('/api/profiles/<int:profile_id>', methods=['GET'])
def get_profile(profile_id):
    db = get_db()
    try:
        cursor = db.cursor()
        cursor.execute("SELECT * FROM profiles WHERE id = ?", (profile_id,))
        row = cursor.fetchone()

        if row is None:
            return jsonify({"error": "Profile not found"}), 404

        profile = {
            "id": row["id"],
            "name": row["name"],
            "browser": row["browser"],
            "folder": row["folder"],
            "notes": row["notes"],
            "proxy": row["proxy"],
            "save_cookies": bool(row["save_cookies"]),
            "clear_session_on_exit": bool(row["clear_session_on_exit"]),
            "project_id": row["project_id"],
            "last_used": row["last_used"]
        }

        return jsonify(profile), 200
    except Exception as e:
        app.logger.error(f"Error fetching profile: {e}", exc_info=True)
        return jsonify({"error": "Failed to load profile"}), 500


@app.route('/api/profiles/by_project/<int:project_id>', methods=['GET'])
def get_profiles_by_project(project_id):
    """API endpoint to get profiles associated with a specific project."""
    db = get_db()
    profiles = db.execute('''
        SELECT prof.*, proj.name AS project_name
        FROM profiles prof
        LEFT JOIN projects proj ON prof.project_id = proj.id
        WHERE prof.project_id = ? AND prof.is_deleted = 0
        ORDER BY prof.name ASC
    ''', (project_id,)).fetchall()

    profiles_list = []
    for row in profiles:
        profile_dict = dict(row)
        if profile_dict['last_used']:
            try:
                dt_object = datetime.datetime.strptime(profile_dict['last_used'], '%Y-%m-%d %H:%M:%S.%f')
            except ValueError:
                dt_object = datetime.datetime.strptime(profile_dict['last_used'], '%Y-%m-%d %H:%M:%S')
            profile_dict['last_used_formatted'] = dt_object.strftime('%B %d, %Y %I:%M %p')
        else:
            profile_dict['last_used_formatted'] = 'Never'
        profile_dict['save_cookies_display'] = 'Yes' if profile_dict['save_cookies'] else 'No'
        profile_dict['clear_session_on_exit_display'] = 'Yes' if profile_dict['clear_session_on_exit'] else 'No'

        profiles_list.append(profile_dict)
    return jsonify(profiles_list), 200



@app.route('/api/launch_profile/<int:profile_id>', methods=['POST'])
def launch_profile(profile_id):
    db = get_db()
    cursor = db.cursor()

    try:
        # 1. Retrieve profile details from the database
        profile = cursor.execute('SELECT * FROM profiles WHERE id = ?', (profile_id,)).fetchone()

        if not profile:
            app.logger.warning(f"Attempted to launch non-existent profile with ID: {profile_id}")
            return jsonify({"status": "error", "message": "Profile not found."}), 404

        browser_type = profile['browser'] # e.g., 'Chrome', 'Firefox', 'Brave'
        profile_folder_path = profile['folder'] # The unique path we created earlier

        # 2. Determine browser executable path and arguments
        # IMPORTANT: Verify these paths match where you place your portable browsers.
        # Ensure the .exe names are correct for your portable versions.
        browser_exe_map = {
            'chrome': os.path.join(app.config['BROWSER_BINARIES_DIR'], 'GoogleChromePortable', 'App', 'Chrome-bin', 'chrome.exe'),
            'firefox': os.path.join(app.config['BROWSER_BINARIES_DIR'], 'FirefoxPortable', 'App', 'Firefox64', 'firefox.exe'),
            'brave': os.path.join(app.config['BROWSER_BINARIES_DIR'], 'BravePortable', 'BravePortable.exe') # Adjust if Brave's portable executable is different
        }

        browser_executable = browser_exe_map.get(browser_type)

        if not browser_executable or not os.path.exists(browser_executable):
            app.logger.error(f"Browser executable not found for {browser_type}: {browser_executable}")
            return jsonify({"status": "error", "message": f"Browser executable for {browser_type} not found. Please ensure it's placed correctly."}), 404

        # Construct command-line arguments for launching the browser with the specific profile
        command = [browser_executable]
        if browser_type == 'chrome' or browser_type == 'brave':
            command.append(f'--user-data-dir={profile_folder_path}')
            # Optional: Add --no-first-run --no-default-browser-check for cleaner startup
            command.extend(['--no-first-run', '--no-default-browser-check'])
        elif browser_type == 'firefox':
            command.append('-profile')
            command.append(profile_folder_path)
            # Optional: Add -no-remote to ensure a new instance is always launched
            command.append('-no-remote')
        else:
            app.logger.error(f"Unsupported browser type for launch: {browser_type}")
            return jsonify({"status": "error", "message": f"Unsupported browser type for launch: {browser_type}"}), 400

        app.logger.info(f"Launching command: {' '.join(command)}")

        

        # 3. Launch the browser
        # Using Popen to launch it without waiting for it to close
        subprocess.Popen(command, close_fds=True) # close_fds=True is good practice on non-Windows, but doesn't hurt on Windows

        # 4. Update last_used timestamp in the database
        current_time = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        cursor.execute('UPDATE profiles SET last_used = ? WHERE id = ?', (current_time, profile_id))
        db.commit()
        app.logger.info(f"Profile '{profile['name']}' (ID: {profile_id}) launched successfully and last_used updated.")

        return jsonify({"status": "success", "message": f"{browser_type} launched for profile {profile['name']}."}), 200

    except Exception as e:
        app.logger.error(f"Error launching profile {profile_id}: {e}", exc_info=True)
        return jsonify({"status": "error", "message": f"Failed to launch browser: {str(e)}"}), 500

@app.route('/api/edit_profile/<int:profile_id>', methods=['PUT'])
def edit_profile(profile_id):
    if not request.is_json:
        return jsonify({"error": "Request must be JSON"}), 400

    data = request.get_json()
    name = data.get('name')
    notes = data.get('notes')
    proxy = data.get('proxy')
    save_cookies = data.get('save_cookies')
    clear_session_on_exit = data.get('clear_session_on_exit')
    project_id = data.get('project_id')

    if not name:
        return jsonify({"error": "Profile name is required!"}), 400

    if project_id is not None:
        try:
            project_id = int(project_id)
        except ValueError:
            return jsonify({"error": "Invalid project ID."}), 400

    db = get_db()
    try:
        cursor = db.cursor()

        # Check if profile exists
        cursor.execute("SELECT * FROM profiles WHERE id = ?", (profile_id,))
        profile = cursor.fetchone()

        if profile is None:
            return jsonify({"error": "Profile not found."}), 404

        # Do not allow changing the browser type or folder path

        cursor.execute('''
            UPDATE profiles
            SET name = ?, notes = ?, proxy = ?, save_cookies = ?, clear_session_on_exit = ?, project_id = ?
            WHERE id = ?
        ''', (name, notes, proxy, save_cookies, clear_session_on_exit, project_id, profile_id))

        db.commit()
        return jsonify({"message": "Profile updated successfully!"}), 200
    except Exception as e:
        db.rollback()
        app.logger.error(f"Error updating profile: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


@app.route('/api/profiles/<int:profile_id>', methods=['DELETE'])
def delete_profile(profile_id):
    db = get_db()
    cursor = db.cursor()

    try:
        # Only select if not already deleted
        profile = cursor.execute(
            'SELECT folder FROM profiles WHERE id = ? AND is_deleted = 0',
            (profile_id,)
        ).fetchone()

        if not profile:
            app.logger.warning(f"Attempted to delete non-existent or already deleted profile with ID: {profile_id}")
            return jsonify({"status": "error", "message": "Profile not found or already deleted."}), 404

        profile_folder_path = profile['folder']

        # Soft delete
        cursor.execute('''
            UPDATE profiles SET is_deleted = 1, deleted_at = CURRENT_TIMESTAMP
            WHERE id = ?
        ''', (profile_id,))
        db.commit()

        app.logger.info(f"Profile ID {profile_id} moved to recycle bin.")

        # (Optional) Log folder path for reference — not deleting here
        if profile_folder_path:
            app.logger.info(f"Profile folder recorded: {profile_folder_path}")

        return jsonify({"status": "success", "message": "Profile moved to recycle bin."}), 200

    except Exception as e:
        db.rollback()
        app.logger.error(f"Error deleting profile {profile_id}: {e}", exc_info=True)
        return jsonify({"status": "error", "message": f"Failed to delete profile: {str(e)}"}), 500
    

@app.route('/api/deleted_profiles', methods=['GET'])
# @login_required
def get_deleted_profiles():
    db = get_db()
    rows = db.execute('''
        SELECT id, name, deleted_at 
        FROM profiles 
        WHERE is_deleted = 1
        ORDER BY deleted_at DESC
    ''').fetchall()
    return jsonify([dict(row) for row in rows]), 200



@app.route('/api/profiles/restore/<int:profile_id>', methods=['POST'])
def restore_profile(profile_id):
    db = get_db()
    cursor = db.cursor()

    try:
        # Check if profile is soft-deleted
        profile = cursor.execute(
            'SELECT id FROM profiles WHERE id = ? AND is_deleted = 1',
            (profile_id,)
        ).fetchone()

        if not profile:
            return jsonify({"status": "error", "message": "Profile not found or is not deleted."}), 404

        # Restore the profile
        cursor.execute(
            '''
            UPDATE profiles
            SET is_deleted = 0, deleted_at = NULL
            WHERE id = ?
            ''',
            (profile_id,)
        )
        db.commit()

        app.logger.info(f"Profile ID {profile_id} restored from recycle bin.")
        return jsonify({"status": "success", "message": "Profile restored successfully."}), 200

    except Exception as e:
        db.rollback()
        app.logger.error(f"Error restoring profile {profile_id}: {e}", exc_info=True)
        return jsonify({"status": "error", "message": f"Failed to restore profile: {str(e)}"}), 500


@app.route('/api/projects/<int:project_id>', methods=['DELETE'])
# @login_required
def delete_project(project_id):
    db = get_db()
    cursor = db.cursor()

    try:
        # 1. Get project to verify existence
        project = cursor.execute('SELECT id FROM projects WHERE id = ?', (project_id,)).fetchone()

        if not project:
            app.logger.warning(f"Attempted to delete non-existent project with ID: {project_id}")
            return jsonify({"status": "error", "message": "Project not found."}), 404

        # 2. Soft-delete the project
        cursor.execute('''
            UPDATE projects
            SET is_deleted = 1,
                deleted_at = CURRENT_TIMESTAMP
            WHERE id = ?
        ''', (project_id,))

        # 3. Soft-delete all associated profiles
        cursor.execute('''
            UPDATE profiles
            SET is_deleted = 1,
                deleted_at = CURRENT_TIMESTAMP
            WHERE project_id = ?
        ''', (project_id,))

        db.commit()
        app.logger.info(f"Project ID {project_id} and associated profiles soft-deleted (moved to recycle bin).")
        return jsonify({"status": "success", "message": "Project moved to recycle bin."}), 200

    except Exception as e:
        db.rollback()
        app.logger.error(f"Error deleting project {project_id}: {e}", exc_info=True)
        return jsonify({"status": "error", "message": f"Failed to delete project: {str(e)}"}), 500

    

@app.route('/api/deleted_projects', methods=['GET'])
# @login_required
def get_deleted_projects():
    db = get_db()
    rows = db.execute('''
        SELECT id, name, deleted_at 
        FROM projects 
        WHERE is_deleted = 1
        ORDER BY deleted_at DESC
    ''').fetchall()
    return jsonify([dict(row) for row in rows]), 200

@app.route('/api/projects/restore/<int:project_id>', methods=['POST'])
def restore_project(project_id):
    db = get_db()
    cursor = db.cursor()

    try:
        project = cursor.execute(
            'SELECT id FROM projects WHERE id = ? AND is_deleted = 1',
            (project_id,)
        ).fetchone()

        if not project:
            return jsonify({"status": "error", "message": "Project not found or already restored."}), 404

        cursor.execute('''
            UPDATE projects
            SET is_deleted = 0,
                deleted_at = NULL
            WHERE id = ?
        ''', (project_id,))

        cursor.execute('''
            UPDATE profiles
            SET is_deleted = 0,
                deleted_at = NULL
            WHERE project_id = ?
        ''', (project_id,))

        db.commit()

        return jsonify({"status": "success", "message": "Project and associated profiles restored."}), 200

    except Exception as e:
        db.rollback()
        return jsonify({"status": "error", "message": str(e)}), 500



@app.route('/api/empty_recycle_bin', methods=['DELETE'])
# @login_required
def empty_recycle_bin():
    db = get_db()
    cursor = db.cursor()

    try:
        # 1. Delete profile folders for profiles marked is_deleted
        deleted_profiles = cursor.execute('SELECT folder FROM profiles WHERE is_deleted = 1').fetchall()
        for profile in deleted_profiles:
            folder_path = profile['folder']
            if folder_path and os.path.exists(folder_path) and os.path.isdir(folder_path):
                try:
                    shutil.rmtree(folder_path)
                    app.logger.info(f"Deleted folder: {folder_path}")
                except Exception as e:
                    app.logger.error(f"Failed to delete folder {folder_path}: {e}", exc_info=True)

        # 2. Delete profiles from DB
        cursor.execute('DELETE FROM profiles WHERE is_deleted = 1')

        # 3. Delete projects from DB
        cursor.execute('DELETE FROM projects WHERE is_deleted = 1')

        db.commit()
        app.logger.info("Recycle bin emptied: Deleted all soft-deleted projects and profiles.")
        return jsonify({"status": "success", "message": "Recycle bin emptied successfully."}), 200

    except Exception as e:
        db.rollback()
        app.logger.error(f"Error emptying recycle bin: {e}", exc_info=True)
        return jsonify({"status": "error", "message": f"Failed to empty recycle bin: {str(e)}"}), 500



@app.route('/api/available_browsers', methods=['GET'])
def get_available_browsers():
    browser_binaries_path = app.config['BROWSER_BINARIES_DIR']
    browser_map = {
        'chrome': 'GoogleChromePortable',
        'firefox': 'FirefoxPortable',
        'brave': 'BravePortable'
    }

    db = get_db()
    response = []

    for browser_key, folder_name in browser_map.items():
        folder_path = os.path.join(browser_binaries_path, folder_name)
        if os.path.exists(folder_path):
            count = db.execute('SELECT COUNT(*) FROM profiles WHERE browser = ?', (browser_key,)).fetchone()[0]
            response.append({
                'browser': browser_key,
                'version': '123.0.0',  # (Optional: Replace this with actual version logic later)
                'profile_count': count
            })

    return jsonify(response), 200



@app.route('/api/open_browser_folder', methods=['POST'])
def open_browser_folder():
    folder_path = app.config['BROWSER_BINARIES_DIR']

    if platform.system() == 'Windows':
        try:
            os.startfile(folder_path)  # ✅ This gives better OS-level handling on Windows
            return jsonify({"success": True})
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500
    else:
        return jsonify({"success": False, "error": "Unsupported OS"}), 400


def download_file(url, dest_path):
    response = requests.get(url, stream=True)
    response.raise_for_status()
    with open(dest_path, 'wb') as f:
        for chunk in response.iter_content(chunk_size=8192):
            f.write(chunk)

def sha256_checksum(file_path):
    sha256 = hashlib.sha256()
    with open(file_path, 'rb') as f:
        for chunk in iter(lambda: f.read(8192), b''):
            sha256.update(chunk)
    return sha256.hexdigest()

@app.route('/api/download_browser', methods=['POST'])
def download_browser():
    browser = request.json.get('browser')
    
    # Load browser manifest
    with open(BROWSER_MANIFEST) as f:
        browsers = json.load(f)

    match = next((b for b in browsers if b['browser'] == browser), None)
    if not match:
        return jsonify({'error': 'Browser not found in manifest'}), 404

    url = match['download_url']
    # expected_checksum = match['checksum']
    zip_filename = f"{browser}.zip"
    zip_path = os.path.join(app.config['BROWSER_BINARIES_DIR'], zip_filename)

    try:
        # Step 1: Download zip
        download_file(url, zip_path)

        # # Step 2: Verify checksum
        # actual_checksum = sha256_checksum(zip_path)
        # if actual_checksum != expected_checksum:
        #     os.remove(zip_path)
        #     return jsonify({'error': 'Checksum mismatch! File may be tampered.'}), 400

        # Step 3: Extract
        extract_dir = app.config['BROWSER_BINARIES_DIR']
        os.makedirs(extract_dir, exist_ok=True)
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            zip_ref.extractall(extract_dir)

        os.remove(zip_path)
        return jsonify({'message': f'{browser} downloaded and extracted successfully.'})

    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route("/uninstall", methods=["POST"])
def uninstall_browser():
    data = request.get_json()
    print("Received uninstall POST:", data)

    browserFolder = data.get("browser_name")  # <-- Match JS key name

    if not browserFolder:
        return jsonify({"success": False, "message": "No browser name provided"}), 400

    browser_path = os.path.join(app.config['BROWSER_BINARIES_DIR'], browserFolder)

    if not os.path.exists(browser_path):
        return jsonify({"success": False, "message": "Browser not found"}), 404

    try:
        shutil.rmtree(browser_path)
        return jsonify({"success": True, "message": f"{browserFolder} uninstalled"})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500
    




@app.route('/export_full_backup', methods=['GET'])
def export_full_backup():
    try:
        # Get database path from config
        db_path = app.config['DATABASE']

        if not os.path.exists(db_path):
            return jsonify({"status": "error", "message": "Database file not found."}), 404

        # Create a temporary zip file
        temp_zip = tempfile.NamedTemporaryFile(delete=False, suffix='.zip')
        zip_path = temp_zip.name

        with zipfile.ZipFile(zip_path, 'w') as zipf:
            # Add the database
            zipf.write(db_path, arcname='profiles.db')

            # Add the profiles folder and subfolders
            profiles_dir = os.path.join(app.root_path, 'profiles')
            if os.path.exists(profiles_dir):
                for root, dirs, files in os.walk(profiles_dir):
                    for file in files:
                        abs_path = os.path.join(root, file)
                        rel_path = os.path.relpath(abs_path, app.root_path)
                        zipf.write(abs_path, arcname=rel_path)

        return send_file(zip_path, as_attachment=True, download_name="browser_manager_backup.zip")

    except Exception as e:
        app.logger.error(f"Error exporting full backup: {e}", exc_info=True)
        return jsonify({"status": "error", "message": f"Export failed: {str(e)}"}), 500


# ------------------------------
# ✅ 1. API: Check if DB is empty
# ------------------------------
@app.route('/api/check_db_empty', methods=['GET'])
def check_db_empty():
    db = get_db()
    project_count = db.execute('SELECT COUNT(*) FROM projects').fetchone()[0]
    profile_count = db.execute('SELECT COUNT(*) FROM profiles').fetchone()[0]
    is_empty = (project_count == 0 and profile_count == 0)
    return jsonify({"isEmpty": is_empty})



import zipfile
import tempfile

@app.route('/import_db', methods=['POST'])
def import_db():
    if 'db_file' not in request.files:
        return jsonify({"status": "error", "message": "No file part in the request."}), 400

    file = request.files['db_file']
    if file.filename == '':
        return jsonify({"status": "error", "message": "No file selected."}), 400

    if file and file.filename.endswith('.zip'):
        try:
            # Create temp directory to extract zip
            temp_dir = tempfile.mkdtemp()
            zip_path = os.path.join(temp_dir, secure_filename(file.filename))
            file.save(zip_path)

            # Extract contents
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                zip_ref.extractall(temp_dir)

            # --- Restore DB ---
            db_path = app.config['DATABASE']
            extracted_db = os.path.join(temp_dir, 'profiles.db')
            if not os.path.exists(extracted_db):
                return jsonify({"status": "error", "message": "Backup does not contain profiles.db"}), 400

            if os.path.exists(db_path):
                backup_path = db_path + ".bak"
                shutil.copy2(db_path, backup_path)
                app.logger.info(f"Backed up existing DB to {backup_path}")

            shutil.copy2(extracted_db, db_path)
            app.logger.info("Restored database from backup.")

            # --- Restore Profiles Folder ---
            extracted_profiles_dir = os.path.join(temp_dir, 'profiles')
            profiles_dir = app.config['PROFILES_DIR']

            if os.path.exists(extracted_profiles_dir):
                if os.path.exists(profiles_dir):
                    shutil.rmtree(profiles_dir)
                    app.logger.info("Deleted old profiles directory.")
                shutil.copytree(extracted_profiles_dir, profiles_dir)
                app.logger.info("Restored profiles directory from backup.")

            return jsonify({"status": "success", "message": "Backup imported successfully."}), 200

        except Exception as e:
            app.logger.error(f"Import failed: {e}", exc_info=True)
            return jsonify({"status": "error", "message": f"Import failed: {str(e)}"}), 500

    return jsonify({"status": "error", "message": "Invalid file format. Please upload a .zip backup."}), 400



 



if __name__ == '__main__':
    # Get port from environment variable, default to 5000
    port = int(os.environ.get('FLASK_APP_PORT', 5000))

    # Disable Flask's reloader in production (packaged) environments
    debug_mode = os.environ.get('FLASK_DEBUG', '0') == '1'
    use_reloader = debug_mode and not getattr(sys, 'frozen', False)

    # Open system default browser
    url = f"http://127.0.0.1:{port}"
    print(f"Flask app starting on {url}, debug={debug_mode}, reloader={use_reloader}")
    webbrowser.open(url)

    app.run(host='127.0.0.1', port=port, debug=debug_mode, use_reloader=use_reloader)
