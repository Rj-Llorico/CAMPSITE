from flask import Flask, jsonify, request, render_template
import sqlite3
import threading
import time
import os

app = Flask(__name__)

# =========================================================
# CONFIGURATION
# =========================================================

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_FILE = os.path.join(BASE_DIR, "balakbak.db")

SIMULATED_DOOR_TIME = 1


# =========================================================
# OWNER LOGIN
# =========================================================

OWNER_USERNAME = "admin"
OWNER_PASSWORD = "admin123"


# =========================================================
# LOCKER DATA
# =========================================================

lockers = {
    1: {
        "status": "AVAILABLE",
        "door": "LOCKED",
        "pin": None,
        "device": False,
        "action": None,
        "timer": None,
        "door_token": 0
    },

    2: {
        "status": "AVAILABLE",
        "door": "LOCKED",
        "pin": None,
        "device": False,
        "action": None,
        "timer": None,
        "door_token": 0
    },

    3: {
        "status": "AVAILABLE",
        "door": "LOCKED",
        "pin": None,
        "device": False,
        "action": None,
        "timer": None,
        "door_token": 0
    }
}


# =========================================================
# LOCKS
# =========================================================

locker_lock = threading.RLock()
emergency_lock = threading.Lock()


# =========================================================
# SYSTEM STATUS
# =========================================================

system_status = {
    "solar_power": 85,
    "battery": 87,
    "voltage": 12.6,
    "current": 3.2,
    "lora": "SIMULATION",
    "raspberry_pi": "WEB ONLY"
}


# =========================================================
# EMERGENCY DATA
# =========================================================

emergency_requests = []
emergency_counter = 0


# =========================================================
# DATABASE CONNECTION
# =========================================================

def get_database():

    return sqlite3.connect(
        DB_FILE,
        timeout=10
    )


# =========================================================
# DATABASE INITIALIZATION
# =========================================================

def init_database():

    connection = get_database()
    cursor = connection.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS lockers (
            id INTEGER PRIMARY KEY,
            status TEXT NOT NULL,
            door TEXT NOT NULL,
            pin TEXT,
            device INTEGER NOT NULL DEFAULT 0
        )
    """)

    for locker_id in range(1, 4):

        cursor.execute(
            "SELECT id FROM lockers WHERE id = ?",
            (locker_id,)
        )

        if cursor.fetchone() is None:

            cursor.execute("""
                INSERT INTO lockers
                (id, status, door, pin, device)
                VALUES (?, ?, ?, ?, ?)
            """, (
                locker_id,
                "AVAILABLE",
                "LOCKED",
                None,
                0
            ))

    connection.commit()
    connection.close()

    print("[DATABASE] Database initialized.")
    print(f"[DATABASE] Using: {DB_FILE}")


# =========================================================
# READ ONE LOCKER
# =========================================================

def read_locker_from_database(locker_id):

    connection = get_database()
    cursor = connection.cursor()

    cursor.execute("""
        SELECT
            id,
            status,
            door,
            pin,
            device
        FROM lockers
        WHERE id = ?
    """, (locker_id,))

    row = cursor.fetchone()

    connection.close()

    return row


# =========================================================
# REFRESH ONE LOCKER FROM DATABASE
# =========================================================

def refresh_locker_from_database(locker_id):

    row = read_locker_from_database(locker_id)

    if not row:
        return False

    with locker_lock:

        lockers[locker_id]["status"] = row[1]
        lockers[locker_id]["door"] = row[2]
        lockers[locker_id]["pin"] = row[3]
        lockers[locker_id]["device"] = bool(row[4])

    return True


# =========================================================
# REFRESH ALL LOCKERS
# =========================================================

def refresh_lockers_from_database():

    connection = get_database()
    cursor = connection.cursor()

    cursor.execute("""
        SELECT
            id,
            status,
            door,
            pin,
            device
        FROM lockers
        ORDER BY id
    """)

    rows = cursor.fetchall()

    connection.close()

    with locker_lock:

        for row in rows:

            locker_id = row[0]

            if locker_id not in lockers:
                continue

            lockers[locker_id]["status"] = row[1]
            lockers[locker_id]["door"] = row[2]
            lockers[locker_id]["pin"] = row[3]
            lockers[locker_id]["device"] = bool(row[4])


# =========================================================
# SAVE LOCKER TO DATABASE
# =========================================================

def save_locker(locker_id):

    locker = lockers[locker_id]

    connection = get_database()
    cursor = connection.cursor()

    cursor.execute("""
        UPDATE lockers
        SET
            status = ?,
            door = ?,
            pin = ?,
            device = ?
        WHERE id = ?
    """, (
        locker["status"],
        locker["door"],
        locker["pin"],
        1 if locker["device"] else 0,
        locker_id
    ))

    connection.commit()
    connection.close()


# =========================================================
# FRONTEND LOCKER DATA
# =========================================================

def locker_data(locker_id):

    locker = lockers[locker_id]

    return {
        "id": locker_id,
        "status": locker["status"],
        "door": locker["door"],
        "device": locker["device"],
        "has_pin": locker["pin"] is not None
    }


def get_all_locker_data():

    result = {}

    for locker_id in range(1, 4):

        result[str(locker_id)] = locker_data(
            locker_id
        )

    return result


# =========================================================
# CANCEL TIMER
# =========================================================

def cancel_locker_timer(locker_id):

    locker = lockers[locker_id]

    timer = locker.get("timer")

    if timer:

        try:
            timer.cancel()
        except Exception:
            pass

    locker["timer"] = None

    # Invalidate previous timer
    locker["door_token"] += 1


# =========================================================
# RESET LOCKER
# =========================================================

def reset_locker_state(locker_id):

    if locker_id not in lockers:

        print(
            f"[RESET ERROR] Locker {locker_id} "
            f"does not exist."
        )

        return False

    with locker_lock:

        print("")
        print("========================================")
        print(
            f"[RESET] RESETTING LOCKER {locker_id}"
        )
        print("========================================")

        # -------------------------------------------------
        # CANCEL ANY OPEN-DOOR TIMER
        # -------------------------------------------------

        cancel_locker_timer(locker_id)

        connection = None

        try:

            connection = get_database()
            cursor = connection.cursor()

            # -------------------------------------------------
            # RESET SQLITE
            # -------------------------------------------------

            cursor.execute("""
                UPDATE lockers
                SET
                    status = 'AVAILABLE',
                    door = 'LOCKED',
                    pin = NULL,
                    device = 0
                WHERE id = ?
            """, (locker_id,))

            connection.commit()

            # -------------------------------------------------
            # VERIFY DATABASE
            # -------------------------------------------------

            cursor.execute("""
                SELECT
                    id,
                    status,
                    door,
                    pin,
                    device
                FROM lockers
                WHERE id = ?
            """, (locker_id,))

            row = cursor.fetchone()

            if row is None:

                print(
                    f"[RESET ERROR] Locker "
                    f"{locker_id} not found in database."
                )

                return False

            print(
                f"[DATABASE] Locker {locker_id} reset:"
            )

            print(
                f"  Status = {row[1]}"
            )

            print(
                f"  Door   = {row[2]}"
            )

            print(
                f"  PIN    = {row[3]}"
            )

            print(
                f"  Device = {row[4]}"
            )

        except Exception as error:

            print(
                f"[DATABASE ERROR] "
                f"Reset Locker {locker_id}: {error}"
            )

            if connection:

                try:
                    connection.rollback()
                except Exception:
                    pass

            return False

        finally:

            if connection:

                connection.close()

        # -------------------------------------------------
        # RESET PYTHON MEMORY
        # -------------------------------------------------

        locker = lockers[locker_id]

        locker["status"] = "AVAILABLE"
        locker["door"] = "LOCKED"
        locker["pin"] = None
        locker["device"] = False
        locker["action"] = None
        locker["timer"] = None

        print(
            f"[MEMORY] Locker {locker_id}: "
            f"AVAILABLE / LOCKED / NO PIN / NO DEVICE"
        )

        print(
            f"[RESET SUCCESS] Locker {locker_id} "
            f"is now AVAILABLE."
        )

        print("========================================")
        print("")

        return True


# =========================================================
# AUTOMATIC DOOR CLOSE
# =========================================================

def simulated_door_close(locker_id, token):

    print(
        f"[SIMULATION] Locker {locker_id}: "
        f"Door timer started "
        f"({SIMULATED_DOOR_TIME}s)"
    )

    time.sleep(SIMULATED_DOOR_TIME)

    with locker_lock:

        locker = lockers.get(locker_id)

        if not locker:
            return

        # -------------------------------------------------
        # IGNORE OLD TIMER
        # -------------------------------------------------

        if locker["door_token"] != token:

            print(
                f"[SIMULATION] Locker {locker_id}: "
                f"Old timer ignored."
            )

            return

        # -------------------------------------------------
        # DOOR ALREADY CLOSED
        # -------------------------------------------------

        if locker["door"] != "OPEN":

            print(
                f"[SIMULATION] Locker {locker_id}: "
                f"Door already closed."
            )

            return

        action = locker.get("action")

        print(
            f"[SIMULATION] Locker {locker_id}: "
            f"Door automatically CLOSED."
        )

        # =================================================
        # RETRIEVE
        # =================================================

        if action == "retrieve":

            locker["door"] = "LOCKED"
            locker["status"] = "AVAILABLE"
            locker["device"] = False
            locker["pin"] = None
            locker["action"] = None
            locker["timer"] = None

            save_locker(locker_id)

            print(
                f"[SIMULATION] Locker {locker_id}: "
                f"Device RETRIEVED."
            )

            return

        # =================================================
        # CHECK
        # =================================================

        if action == "check":

            locker["door"] = "LOCKED"
            locker["device"] = True
            locker["status"] = "CHARGING"
            locker["action"] = None
            locker["timer"] = None

            save_locker(locker_id)

            print(
                f"[SIMULATION] Locker {locker_id}: "
                f"Device still inside."
            )

            print(
                f"[SIMULATION] Locker {locker_id}: "
                f"CHARGING."
            )

            return

        # =================================================
        # DEPOSIT
        # =================================================

        if action == "deposit":

            locker["door"] = "LOCKED"
            locker["device"] = True
            locker["status"] = "CHARGING"
            locker["action"] = None
            locker["timer"] = None

            save_locker(locker_id)

            print(
                f"[SIMULATION] Locker {locker_id}: "
                f"Device detected."
            )

            print(
                f"[SIMULATION] Locker {locker_id}: "
                f"CHARGING."
            )

            return

        # =================================================
        # UNKNOWN ACTION
        # =================================================

        locker["door"] = "LOCKED"
        locker["timer"] = None

        save_locker(locker_id)


# =========================================================
# OPEN DOOR
# =========================================================
# KIOSK ONLY
# =========================================================

def open_door(locker_id):

    with locker_lock:

        locker = lockers.get(locker_id)

        if not locker:
            return False

        cancel_locker_timer(locker_id)

        token = locker["door_token"]

        locker["door"] = "OPEN"

        save_locker(locker_id)

        print(
            f"[SIMULATION] Locker {locker_id}: "
            f"DOOR OPEN"
        )

        timer = threading.Timer(
            SIMULATED_DOOR_TIME,
            simulated_door_close,
            args=(locker_id, token)
        )

        timer.daemon = True

        locker["timer"] = timer

        timer.start()

        return True


# =========================================================
# HOME / KIOSK
# =========================================================

@app.route("/")
def index():

    return render_template("index.html")


# =========================================================
# OWNER APP
# =========================================================

@app.route("/app")
def owner_app():

    return render_template("app.html")


# =========================================================
# OWNER LOGIN
# =========================================================

@app.route("/api/login", methods=["POST"])
def owner_login():

    data = request.get_json(silent=True) or {}

    username = str(
        data.get("username", "")
    ).strip()

    password = str(
        data.get("password", "")
    )

    if username == "":

        return jsonify({
            "success": False,
            "message": "Please enter your username."
        })

    if password == "":

        return jsonify({
            "success": False,
            "message": "Please enter your password."
        })

    if (
        username == OWNER_USERNAME
        and
        password == OWNER_PASSWORD
    ):

        print("[OWNER APP] Login successful.")

        return jsonify({
            "success": True,
            "message": "Login successful.",
            "username": username
        })

    print("[OWNER APP] Login failed.")

    return jsonify({
        "success": False,
        "message": "Invalid username or password."
    })


# =========================================================
# GET ALL LOCKERS
# =========================================================

@app.route("/api/lockers", methods=["GET"])
def get_lockers():

    refresh_lockers_from_database()

    with locker_lock:

        result = get_all_locker_data()

    return jsonify(result)


# =========================================================
# GET ONE LOCKER
# =========================================================

@app.route("/api/lockers/<int:locker_id>", methods=["GET"])
def get_locker(locker_id):

    if locker_id not in lockers:

        return jsonify({
            "success": False,
            "message": "Locker does not exist."
        }), 404

    refresh_locker_from_database(locker_id)

    with locker_lock:

        data = locker_data(locker_id)

    return jsonify({
        "success": True,
        "locker": data
    })


# =========================================================
# CREATE PIN
# =========================================================

@app.route(
    "/api/lockers/<int:locker_id>/create-pin",
    methods=["POST"]
)
def create_pin(locker_id):

    if locker_id not in lockers:

        return jsonify({
            "success": False,
            "message": "Locker does not exist."
        }), 404

    data = request.get_json(silent=True) or {}

    pin = str(
        data.get("pin", "")
    ).strip()

    if not pin.isdigit():

        return jsonify({
            "success": False,
            "message": "PIN must contain numbers only."
        })

    if len(pin) != 4:

        return jsonify({
            "success": False,
            "message": "PIN must be exactly 4 digits."
        })

    with locker_lock:

        refresh_locker_from_database(locker_id)

        locker = lockers[locker_id]

        if locker["status"] != "AVAILABLE":

            return jsonify({
                "success": False,
                "message": "Locker is not available."
            })

        locker["pin"] = pin
        locker["device"] = False
        locker["action"] = "deposit"
        locker["status"] = "AVAILABLE"
        locker["door"] = "LOCKED"

        save_locker(locker_id)

        current_data = locker_data(locker_id)

    print(
        f"[SIMULATION] Locker {locker_id}: "
        f"PIN CREATED."
    )

    return jsonify({
        "success": True,
        "message": "PIN created successfully.",
        "locker": current_data
    })


# =========================================================
# SET ACTION
# =========================================================

@app.route(
    "/api/lockers/<int:locker_id>/action",
    methods=["POST"]
)
def set_action(locker_id):

    if locker_id not in lockers:

        return jsonify({
            "success": False,
            "message": "Locker does not exist."
        }), 404

    data = request.get_json(silent=True) or {}

    action = str(
        data.get("action", "")
    ).strip().lower()

    print(
        f"[API] Locker {locker_id}: "
        f"Received action = {action}"
    )

    # =====================================================
    # RESET
    # =====================================================

    if action == "reset":

        print(
            f"[API] OWNER RESET REQUEST "
            f"FOR LOCKER {locker_id}"
        )

        success = reset_locker_state(locker_id)

        if not success:

            return jsonify({
                "success": False,
                "message": "Unable to reset locker."
            }), 500

        refresh_locker_from_database(locker_id)

        with locker_lock:

            current_data = locker_data(locker_id)

        return jsonify({
            "success": True,
            "message":
                f"Locker {locker_id} reset successfully.",
            "action": "reset",
            "locker": current_data
        })


    # =====================================================
    # NORMAL KIOSK ACTIONS
    # =====================================================

    if action not in [
        "deposit",
        "retrieve",
        "check"
    ]:

        return jsonify({
            "success": False,
            "message": "Invalid action."
        }), 400

    with locker_lock:

        refresh_locker_from_database(locker_id)

        locker = lockers[locker_id]

        if locker["pin"] is None:

            return jsonify({
                "success": False,
                "message":
                    "No PIN is registered for this locker."
            })

        # -------------------------------------------------
        # DEPOSIT
        # -------------------------------------------------

        if action == "deposit":

            if locker["device"]:

                return jsonify({
                    "success": False,
                    "message":
                        "A device is already inside this locker."
                })

        # -------------------------------------------------
        # RETRIEVE / CHECK
        # -------------------------------------------------

        elif action in [
            "retrieve",
            "check"
        ]:

            if not locker["device"]:

                return jsonify({
                    "success": False,
                    "message":
                        "No device is currently inside this locker."
                })

        locker["action"] = action

        save_locker(locker_id)

    print(
        f"[SIMULATION] Locker {locker_id}: "
        f"Action set to {action}."
    )

    return jsonify({
        "success": True,
        "action": action
    })


# =========================================================
# DEDICATED RESET ENDPOINT
# =========================================================
# OWNER APP USES THIS ENDPOINT
#
# POST:
# /api/lockers/1/reset
# /api/lockers/2/reset
# /api/lockers/3/reset
# =========================================================

@app.route(
    "/api/lockers/<int:locker_id>/reset",
    methods=["POST"]
)
def dedicated_reset_locker(locker_id):

    print("")
    print("========================================")
    print(
        f"[API] RESET REQUEST RECEIVED "
        f"FOR LOCKER {locker_id}"
    )
    print("========================================")

    if locker_id not in lockers:

        print(
            f"[API] Locker {locker_id} does not exist."
        )

        return jsonify({
            "success": False,
            "message": "Locker does not exist."
        }), 404

    success = reset_locker_state(locker_id)

    if not success:

        print(
            f"[API] RESET FAILED "
            f"FOR LOCKER {locker_id}"
        )

        return jsonify({
            "success": False,
            "message": "Unable to reset locker."
        }), 500

    refresh_locker_from_database(locker_id)

    with locker_lock:

        current_data = locker_data(locker_id)

    print(
        f"[API] RESET COMPLETE "
        f"FOR LOCKER {locker_id}"
    )

    print(
        f"[API] Final state: "
        f"{current_data}"
    )

    return jsonify({
        "success": True,
        "message":
            f"Locker {locker_id} reset successfully.",
        "locker": current_data
    })


# =========================================================
# UNLOCK LOCKER
# =========================================================
# KIOSK ONLY
# =========================================================

@app.route(
    "/api/lockers/<int:locker_id>/unlock",
    methods=["POST"]
)
def unlock_locker(locker_id):

    if locker_id not in lockers:

        return jsonify({
            "success": False,
            "message": "Locker does not exist."
        }), 404

    with locker_lock:

        refresh_locker_from_database(locker_id)

        locker = lockers[locker_id]

        if locker["pin"] is None:

            return jsonify({
                "success": False,
                "message":
                    "No valid PIN found for this locker."
            })

        action = locker.get("action")

        # -------------------------------------------------
        # DETERMINE ACTION
        # -------------------------------------------------

        if action not in [
            "deposit",
            "retrieve",
            "check"
        ]:

            if locker["device"]:

                action = "check"

            else:

                action = "deposit"

            locker["action"] = action

        # -------------------------------------------------
        # DEPOSIT
        # -------------------------------------------------

        if action == "deposit":

            if locker["device"]:

                return jsonify({
                    "success": False,
                    "message":
                        "Device already inside this locker."
                })

        # -------------------------------------------------
        # RETRIEVE / CHECK
        # -------------------------------------------------

        if action in [
            "retrieve",
            "check"
        ]:

            if not locker["device"]:

                return jsonify({
                    "success": False,
                    "message":
                        "No device is inside this locker."
                })

        # -------------------------------------------------
        # OPEN DOOR
        # -------------------------------------------------

        success = open_door(locker_id)

        if not success:

            return jsonify({
                "success": False,
                "message":
                    "Unable to unlock locker."
            }), 500

        locker["door"] = "OPEN"
        locker["action"] = action
        locker["status"] = "UNAVAILABLE"

        save_locker(locker_id)

        current_data = locker_data(locker_id)

    print(
        f"[SIMULATION] Locker {locker_id}: "
        f"UNLOCKED for {action}."
    )

    return jsonify({
        "success": True,
        "message": "Locker unlocked.",
        "action": action,
        "locker": current_data
    })


# =========================================================
# VERIFY PIN
# =========================================================

@app.route(
    "/api/lockers/<int:locker_id>/verify-pin",
    methods=["POST"]
)
def verify_pin(locker_id):

    if locker_id not in lockers:

        return jsonify({
            "success": False,
            "message": "Locker does not exist."
        }), 404

    data = request.get_json(silent=True) or {}

    pin = str(
        data.get("pin", "")
    ).strip()

    refresh_locker_from_database(locker_id)

    with locker_lock:

        locker = lockers[locker_id]

        if locker["pin"] is None:

            return jsonify({
                "success": False,
                "message":
                    "No PIN is registered for this locker."
            })

        if pin != locker["pin"]:

            print(
                f"[SIMULATION] Locker {locker_id}: "
                f"Incorrect PIN."
            )

            return jsonify({
                "success": False,
                "message": "Incorrect PIN."
            })

    print(
        f"[SIMULATION] Locker {locker_id}: "
        f"PIN VERIFIED."
    )

    return jsonify({
        "success": True,
        "message": "PIN verified."
    })


# =========================================================
# SYSTEM STATUS
# =========================================================

@app.route("/api/status", methods=["GET"])
def get_status():

    refresh_lockers_from_database()

    status = dict(system_status)

    with locker_lock:

        status["lockers"] = get_all_locker_data()

    return jsonify(status)


# =========================================================
# EMERGENCY SEND
# =========================================================

@app.route(
    "/api/emergency/send",
    methods=["POST"]
)
def emergency():

    global emergency_counter

    data = request.get_json(silent=True) or {}

    accident_type = data.get(
        "type",
        "Other"
    )

    description = data.get(
        "description",
        ""
    )

    location = data.get(
        "location",
        "Mount Balakbak Campsite"
    )

    with emergency_lock:

        emergency_counter += 1

        emergency_request = {
            "id": emergency_counter,
            "type": accident_type,
            "description": description,
            "location": location,
            "status": "NEEDS ASSISTANCE",
            "timestamp": time.strftime(
                "%Y-%m-%d %H:%M:%S"
            )
        }

        emergency_requests.append(
            emergency_request
        )

    print("")
    print("======================================")
    print("🚨 EMERGENCY REQUEST RECEIVED")
    print(f"Type: {accident_type}")

    if description:
        print(f"Description: {description}")

    print(f"Location: {location}")
    print("======================================")
    print("")

    return jsonify({
        "success": True,
        "message":
            "Emergency assistance requested.",
        "emergency":
            emergency_request
    })


# =========================================================
# GET EMERGENCY
# =========================================================

@app.route(
    "/api/emergency",
    methods=["GET"]
)
def get_emergency_requests():

    with emergency_lock:

        requests_copy = list(
            emergency_requests
        )

    return jsonify({
        "success": True,
        "requests": requests_copy
    })


# =========================================================
# ACKNOWLEDGE EMERGENCY
# =========================================================

@app.route(
    "/api/emergency/<int:emergency_id>/acknowledge",
    methods=["POST"]
)
def acknowledge_emergency(emergency_id):

    with emergency_lock:

        for emergency_request in emergency_requests:

            if (
                emergency_request["id"]
                ==
                emergency_id
            ):

                emergency_request[
                    "status"
                ] = "RESCUE IS COMING"

                return jsonify({
                    "success": True,
                    "message":
                        "Emergency request acknowledged.",
                    "emergency":
                        emergency_request
                })

    return jsonify({
        "success": False,
        "message":
            "Emergency request not found."
    }), 404


# =========================================================
# CLEAR EMERGENCY
# =========================================================

@app.route(
    "/api/emergency/clear",
    methods=["POST"]
)
def clear_emergency_requests():

    with emergency_lock:

        emergency_requests.clear()

    return jsonify({
        "success": True,
        "message":
            "Emergency requests cleared."
    })


# =========================================================
# RESET ENTIRE SYSTEM
# =========================================================

@app.route(
    "/api/reset",
    methods=["POST"]
)
def reset_system():

    print("")
    print(
        "[API] ENTIRE SYSTEM RESET REQUESTED"
    )

    results = []

    for locker_id in range(1, 4):

        success = reset_locker_state(
            locker_id
        )

        results.append({
            "locker_id": locker_id,
            "success": success
        })

    all_success = all(
        item["success"]
        for item in results
    )

    if all_success:

        print(
            "[SIMULATION] ENTIRE SYSTEM RESET SUCCESSFUL."
        )

        return jsonify({
            "success": True,
            "message":
                "All lockers reset.",
            "lockers":
                results
        })

    return jsonify({
        "success": False,
        "message":
            "Some lockers could not be reset.",
        "lockers":
            results
    }), 500


# =========================================================
# START SERVER
# =========================================================

if __name__ == "__main__":

    init_database()

    try:

        refresh_lockers_from_database()

    except Exception as error:

        print(
            f"[DATABASE ERROR] {error}"
        )

    print("")
    print("========================================")
    print(" BALAKBAK SMART CHARGING LOCKER")
    print(" SHARED KIOSK + OWNER APP")
    print(" BROWSER SIMULATION MODE")
    print("========================================")

    print("")
    print("Backend       : Flask")
    print("Database      : SQLite")
    print(f"Database File : {DB_FILE}")
    print("Kiosk         : index.html")
    print("Owner App     : app.html")
    print("Shared State  : ENABLED")
    print("Raspberry Pi  : NOT REQUIRED")
    print("Door Sensor   : SIMULATED")
    print("Lock          : SIMULATED")

    print("")
    print("Kiosk:")
    print("http://127.0.0.1:5000")

    print("")
    print("Owner App:")
    print("http://127.0.0.1:5000/app")

    print("")
    print("Owner Login:")
    print("Username: admin")
    print("Password: admin123")

    print("")
    print(
        f"Kiosk door automatically closes "
        f"after {SIMULATED_DOOR_TIME} seconds."
    )

    print("")
    print("Owner control:")
    print("RESET LOCKER ONLY")

    print("")
    print("========================================")
    print("SERVER STARTING...")
    print("========================================")
    print("")

    app.run(
        host="0.0.0.0",
        port=5000,
        debug=True,
        use_reloader=False
    )