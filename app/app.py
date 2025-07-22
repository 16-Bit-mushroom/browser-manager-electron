import os
import sqlite3
from flask import Flask, render_template, request, redirect, url_for, g, jsonify
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

# --- Add Argument Parsing ---
parser = argparse.ArgumentParser(description='Flask Backend for Browser Manager.')
parser.add_argument('--user-data-path', type=str, help='Path to store user data (profiles, database).')
args = parser.parse_args()
# --- End Argument Parsing ---

app = Flask(__name__)

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
app.config['BROWSER_BINARIES_DIR'] = os.path.join(READ_ONLY_RESOURCES_PATH, 'browser_binaries') # This is the key change!
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
                last_used TIMESTAMP DEFAULT CURRENT_TIMESTAMP
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
                FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE SET NULL
            )
        ''')
        db.commit()
        print("Database initialized.")

# Call init_db when the application starts
with app.app_context():
    init_db()

# --- Routes for serving HTML pages ---
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/new-project.html')
def new_project_page():
    return render_template('new-project.html')

@app.route('/new-profile.html')
def new_profile_page():
    return render_template('new-profile.html')

@app.route('/edit-profile.html')
def edit_profile_page():
    return render_template('edit-profile.html')

@app.route('/edit-project.html')
def edit_project_page():
    return render_template('edit-project.html')

@app.route('/projects.html')
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
def browsers_page():
    return render_template('browsers.html')


@app.route('/recycle-bin.html')
def recycle_bin_page():
    return render_template('recycle-bin.html')


@app.route('/settings.html')
def settings_page():
    return render_template('settings.html')

# --- API Endpoints ---

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
    projects = db.execute('''
        SELECT p.id, p.name, p.notes, p.last_used, COUNT(prof.id) AS profile_count
        FROM projects p
        LEFT JOIN profiles prof ON p.id = prof.project_id
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
        WHERE prof.project_id = ?
        ORDER BY prof.name ASC
    ''', (project_id,)).fetchall()

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
        # 1. Get the profile's folder path before deleting from DB
        profile = cursor.execute('SELECT folder FROM profiles WHERE id = ?', (profile_id,)).fetchone()

        if not profile:
            app.logger.warning(f"Attempted to delete non-existent profile with ID: {profile_id}")
            return jsonify({"status": "error", "message": "Profile not found."}), 404

        profile_folder_path = profile['folder']

        # 2. Delete the profile from the database
        cursor.execute('DELETE FROM profiles WHERE id = ?', (profile_id,))
        db.commit()
        app.logger.info(f"Profile ID {profile_id} deleted from database.")

        # 3. Delete the associated profile folder from the file system
        if os.path.exists(profile_folder_path) and os.path.isdir(profile_folder_path):
            try:
                shutil.rmtree(profile_folder_path) # Use rmtree to remove non-empty directories
                app.logger.info(f"Profile folder deleted: {profile_folder_path}")
            except OSError as e:
                app.logger.error(f"Error deleting profile folder {profile_folder_path}: {e}", exc_info=True)
                # Even if folder deletion fails, we report DB deletion success
                return jsonify({"status": "success", "message": "Profile deleted from database, but folder cleanup failed. Check logs."}), 200
        else:
            app.logger.warning(f"Profile folder not found for ID {profile_id}: {profile_folder_path}. Skipping file system cleanup.")

        return jsonify({"status": "success", "message": "Profile deleted successfully."}), 200

    except Exception as e:
        db.rollback()
        app.logger.error(f"Error deleting profile {profile_id}: {e}", exc_info=True)
        return jsonify({"status": "error", "message": f"Failed to delete profile: {str(e)}"}), 500

@app.route('/api/projects/<int:project_id>', methods=['DELETE'])
def delete_project(project_id):
    db = get_db()
    cursor = db.cursor()

    try:
        # 1. Get all profiles associated with this project to delete their folders
        associated_profiles = cursor.execute('SELECT id, folder FROM profiles WHERE project_id = ?', (project_id,)).fetchall()

        # 2. Delete associated profile folders from the file system
        for profile in associated_profiles:
            profile_folder_path = profile['folder']
            if os.path.exists(profile_folder_path) and os.path.isdir(profile_folder_path):
                try:
                    shutil.rmtree(profile_folder_path)
                    app.logger.info(f"Deleted associated profile folder: {profile_folder_path} for project {project_id}")
                except OSError as e:
                    app.logger.error(f"Error deleting associated profile folder {profile_folder_path} for project {project_id}: {e}", exc_info=True)
                    # Continue with DB deletion even if folder deletion fails for one profile
            else:
                app.logger.warning(f"Associated profile folder not found: {profile_folder_path} for project {project_id}. Skipping file system cleanup.")

        # 3. Delete profiles associated with this project from the database
        # ON DELETE SET NULL on the FK means profiles will have project_id set to NULL if project is deleted.
        # If you want to CASCADE DELETE, you'd change the FK definition in init_db().
        # For now, let's explicitly delete them to ensure clean removal.
        cursor.execute('DELETE FROM profiles WHERE project_id = ?', (project_id,))
        app.logger.info(f"Deleted profiles associated with project ID {project_id} from database.")


        # 4. Delete the project itself from the database
        cursor.execute('DELETE FROM projects WHERE id = ?', (project_id,))
        db.commit()
        app.logger.info(f"Project ID {project_id} deleted from database.")
        return jsonify({"status": "success", "message": "Project and associated profiles deleted successfully."}), 200

    except Exception as e:
        db.rollback()
        app.logger.error(f"Error deleting project {project_id}: {e}", exc_info=True)
        return jsonify({"status": "error", "message": f"Failed to delete project: {str(e)}"}), 500

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


# @app.route('/api/open_browser_folder', methods=['POST'])
# def open_browser_folder():
#     try:
#         if platform.system() == 'Windows':
#             os.startfile(folder_path)
#         elif platform.system() == 'Darwin':  # macOS
#             subprocess.Popen(['open', folder_path])
#         else:  # Linux
#             subprocess.Popen(['xdg-open', folder_path])
#         return jsonify({"message": "Folder opened"}), 200
#     except Exception as e:
#         return jsonify({"error": str(e)}), 500


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


# --- MODIFIED Flask RUN block at the end of app.py ---
if __name__ == '__main__':
    # Get port from environment variable set by Electron, default to 5000
    port = int(os.environ.get('FLASK_APP_PORT', 5000))
    
    # Disable Flask's reloader in production (packaged) environments
    debug_mode = os.environ.get('FLASK_DEBUG', '0') == '1'
    use_reloader = debug_mode and not getattr(sys, 'frozen', False)

    print(f"Flask app starting on port {port}, debug={debug_mode}, reloader={use_reloader}")
    
    app.run(host='127.0.0.1', port=port, debug=debug_mode, use_reloader=use_reloader)