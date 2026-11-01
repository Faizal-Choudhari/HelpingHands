import os, sqlite3, csv, io
from datetime import datetime, date
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, session, flash, g, Response, send_from_directory
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DB_PATH = os.path.join(BASE_DIR, "instance", "volunteer_management.db")
UPLOAD_DIR = os.path.join(BASE_DIR, "static", "uploads")
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "pdf", "doc", "docx"}

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "change-this-secret-key-before-deployment")
app.config["MAX_CONTENT_LENGTH"] = 8 * 1024 * 1024
app.config["UPLOAD_FOLDER"] = UPLOAD_DIR

def get_db():
    if "db" not in g:
        os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db

@app.teardown_appcontext
def close_db(error=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    """Create the database schema and seed demo records when the DB is empty.

    The connection stays open until all schema and seed queries have completed.
    The instance directory is created before SQLite tries to open the file.
    """
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")

    try:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS users (
          id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, email TEXT NOT NULL UNIQUE,
          phone TEXT, password TEXT NOT NULL, role TEXT NOT NULL CHECK(role IN ('admin','volunteer','coordinator')),
          status TEXT NOT NULL DEFAULT 'approved', created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS volunteer_profiles (
          user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
          address TEXT, age INTEGER, skills TEXT, interests TEXT, availability TEXT
        );
        CREATE TABLE IF NOT EXISTS events (
          id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, description TEXT, category TEXT,
          event_date TEXT NOT NULL, start_time TEXT, end_time TEXT, venue TEXT,
          capacity INTEGER NOT NULL DEFAULT 20, required_skills TEXT, registration_deadline TEXT,
          coordinator_id INTEGER REFERENCES users(id), status TEXT NOT NULL DEFAULT 'upcoming',
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS registrations (
          id INTEGER PRIMARY KEY AUTOINCREMENT, event_id INTEGER NOT NULL REFERENCES events(id),
          volunteer_id INTEGER NOT NULL REFERENCES users(id), status TEXT NOT NULL DEFAULT 'pending',
          applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, UNIQUE(event_id, volunteer_id)
        );
        CREATE TABLE IF NOT EXISTS attendance (
          id INTEGER PRIMARY KEY AUTOINCREMENT, event_id INTEGER NOT NULL REFERENCES events(id),
          volunteer_id INTEGER NOT NULL REFERENCES users(id), status TEXT NOT NULL DEFAULT 'present',
          hours REAL NOT NULL DEFAULT 0, marked_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          UNIQUE(event_id, volunteer_id)
        );
        CREATE TABLE IF NOT EXISTS activity_reports (
          id INTEGER PRIMARY KEY AUTOINCREMENT, event_id INTEGER NOT NULL REFERENCES events(id),
          volunteer_id INTEGER NOT NULL REFERENCES users(id), activities TEXT NOT NULL,
          description TEXT, hours REAL NOT NULL DEFAULT 0, achievements TEXT, challenges TEXT,
          attachment TEXT, status TEXT NOT NULL DEFAULT 'pending', coordinator_feedback TEXT,
          submitted_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS notifications (
          id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL REFERENCES users(id),
          message TEXT NOT NULL, is_read INTEGER NOT NULL DEFAULT 0,
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS announcements (
          id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, message TEXT NOT NULL,
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        """)

        # Seed demonstration accounts only when the database has no users.
        # Existing users, events, registrations and reports are not overwritten.
        count = db.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        if count == 0:
            demo = [
                ("System Admin", "admin@ngo.org", "9000000001", "admin123", "admin", "approved"),
                ("Demo Volunteer", "volunteer@ngo.org", "9000000002", "volunteer123", "volunteer", "approved"),
                ("Event Coordinator", "coordinator@ngo.org", "9000000003", "coord123", "coordinator", "approved")
            ]
            for name, email, phone, pw, role, status in demo:
                cur = db.execute(
                    "INSERT INTO users(name,email,phone,password,role,status) VALUES(?,?,?,?,?,?)",
                    (name, email, phone, generate_password_hash(pw), role, status)
                )
                if role == "volunteer":
                    db.execute(
                        "INSERT INTO volunteer_profiles(user_id,skills,interests,availability) VALUES(?,?,?,?)",
                        (cur.lastrowid, "Teaching, First Aid", "Education, Community", "Weekends")
                    )

            db.execute("""INSERT INTO events(
                title,description,category,event_date,start_time,end_time,venue,capacity,
                required_skills,registration_deadline,coordinator_id,status
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""", (
                "Community Clean-up Drive",
                "Join us to clean and improve a local public space.",
                "Environment", date.today().isoformat(), "09:00", "13:00",
                "Community Park", 30, "Teamwork", date.today().isoformat(), 3, "upcoming"
            ))
            db.execute(
                "INSERT INTO announcements(title,message) VALUES(?,?)",
                ("Welcome to the NGO Volunteer Portal",
                 "Explore opportunities, register for events, and record your contribution.")
            )

        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        # Close only after all queries, including the users count and seed logic.
        db.close()


def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not session.get("user_id"):
            flash("Please log in to continue.", "warning")
            return redirect(url_for("login"))
        return fn(*args, **kwargs)
    return wrapper

def roles_required(*roles):
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            if not session.get("user_id"):
                return redirect(url_for("login"))
            if session.get("role") not in roles:
                flash("You do not have permission to access that page.", "danger")
                return redirect(url_for("dashboard"))
            return fn(*args, **kwargs)
        return wrapper
    return decorator

def notify(user_id, message):
    get_db().execute("INSERT INTO notifications(user_id,message) VALUES(?,?)", (user_id,message))
    get_db().commit()

@app.context_processor
def inject_globals():
    unread = 0
    if session.get("user_id"):
        unread = get_db().execute("SELECT COUNT(*) FROM notifications WHERE user_id=? AND is_read=0",
                                  (session["user_id"],)).fetchone()[0]
    return {"unread_notifications": unread, "current_year": date.today().year}

@app.route("/")
def home():
    db = get_db()
    events = db.execute("SELECT * FROM events WHERE status!='cancelled' ORDER BY event_date LIMIT 3").fetchall()
    stats = {
      "volunteers": db.execute("SELECT COUNT(*) FROM users WHERE role='volunteer' AND status='approved'").fetchone()[0],
      "events": db.execute("SELECT COUNT(*) FROM events WHERE status!='cancelled'").fetchone()[0],
      "hours": db.execute("SELECT COALESCE(SUM(hours),0) FROM attendance WHERE status IN ('present','late')").fetchone()[0]
    }
    return render_template("home.html", events=events, stats=stats)

@app.route("/register", methods=["GET","POST"])
def register():
    if request.method == "POST":
        name=request.form.get("name","").strip()
        email=request.form.get("email","").strip().lower()
        phone=request.form.get("phone","").strip()
        password=request.form.get("password","")
        if not name or not email or len(password) < 8:
            flash("Enter your name and email, and use a password of at least 8 characters.", "danger")
            return render_template("register.html")
        db=get_db()
        try:
            cur=db.execute("INSERT INTO users(name,email,phone,password,role,status) VALUES(?,?,?,?,?,?)",
                           (name,email,phone,generate_password_hash(password),"volunteer","pending"))
            db.execute("INSERT INTO volunteer_profiles(user_id,address,age,skills,interests,availability) VALUES(?,?,?,?,?,?)",
                       (cur.lastrowid,request.form.get("address"),request.form.get("age") or None,
                        request.form.get("skills"),request.form.get("interests"),request.form.get("availability")))
            db.commit()
            flash("Registration submitted. An administrator must approve your account before you can log in.", "success")
            return redirect(url_for("login"))
        except sqlite3.IntegrityError:
            flash("An account with that email already exists.", "danger")
    return render_template("register.html")

@app.route("/login", methods=["GET","POST"])
def login():
    if request.method == "POST":
        email=request.form.get("email","").strip().lower()
        user=get_db().execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
        if user and check_password_hash(user["password"],request.form.get("password","")):
            if user["status"] != "approved":
                flash("Your account is pending approval or has been disabled. Please contact the NGO administrator.", "warning")
                return render_template("login.html")
            session.clear()
            session.update(user_id=user["id"],name=user["name"],role=user["role"],email=user["email"])
            return redirect(url_for("dashboard"))
        flash("Invalid email or password.", "danger")
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear()
    flash("You have been logged out.", "success")
    return redirect(url_for("home"))

@app.route("/dashboard")
@login_required
def dashboard():
    db=get_db(); role=session["role"]; uid=session["user_id"]
    if role=="admin":
        stats={
          "volunteers":db.execute("SELECT COUNT(*) FROM users WHERE role='volunteer'").fetchone()[0],
          "pending":db.execute("SELECT COUNT(*) FROM users WHERE role='volunteer' AND status='pending'").fetchone()[0],
          "events":db.execute("SELECT COUNT(*) FROM events").fetchone()[0],
          "hours":db.execute("SELECT COALESCE(SUM(hours),0) FROM attendance WHERE status IN ('present','late')").fetchone()[0],
          "reports":db.execute("SELECT COUNT(*) FROM activity_reports WHERE status='pending'").fetchone()[0]
        }
        recent=db.execute("""SELECT r.*,u.name volunteer,e.title event_title FROM registrations r
                             JOIN users u ON u.id=r.volunteer_id JOIN events e ON e.id=r.event_id
                             ORDER BY r.applied_at DESC LIMIT 6""").fetchall()
        return render_template("dashboard.html",stats=stats,recent=recent)
    if role=="volunteer":
        stats={
          "events":db.execute("SELECT COUNT(*) FROM registrations WHERE volunteer_id=? AND status='approved'",(uid,)).fetchone()[0],
          "hours":db.execute("SELECT COALESCE(SUM(hours),0) FROM attendance WHERE volunteer_id=? AND status IN ('present','late')",(uid,)).fetchone()[0],
          "pending":db.execute("SELECT COUNT(*) FROM registrations WHERE volunteer_id=? AND status='pending'",(uid,)).fetchone()[0],
          "reports":db.execute("SELECT COUNT(*) FROM activity_reports WHERE volunteer_id=?",(uid,)).fetchone()[0]
        }
        myevents=db.execute("""SELECT e.*,r.status application_status FROM registrations r JOIN events e ON e.id=r.event_id
                               WHERE r.volunteer_id=? ORDER BY e.event_date LIMIT 6""",(uid,)).fetchall()
        return render_template("dashboard.html",stats=stats,myevents=myevents)
    events=db.execute("""SELECT e.*,COUNT(r.id) registered FROM events e LEFT JOIN registrations r ON r.event_id=e.id AND r.status='approved'
                         WHERE e.coordinator_id=? GROUP BY e.id ORDER BY e.event_date""",(uid,)).fetchall()
    stats={"events":len(events),"volunteers":sum(e["registered"] for e in events),
           "reports":db.execute("""SELECT COUNT(*) FROM activity_reports ar JOIN events e ON e.id=ar.event_id
                                  WHERE e.coordinator_id=? AND ar.status='pending'""",(uid,)).fetchone()[0]}
    return render_template("dashboard.html",stats=stats,coordinator_events=events)

@app.route("/profile", methods=["GET","POST"])
@login_required
def profile():
    db=get_db(); uid=session["user_id"]
    user=db.execute("SELECT * FROM users WHERE id=?",(uid,)).fetchone()
    profile=db.execute("SELECT * FROM volunteer_profiles WHERE user_id=?",(uid,)).fetchone()
    if request.method=="POST":
        db.execute("UPDATE users SET name=?,phone=? WHERE id=?",
                   (request.form.get("name","").strip(),request.form.get("phone","").strip(),uid))
        if session["role"]=="volunteer":
            db.execute("""INSERT INTO volunteer_profiles(user_id,address,age,skills,interests,availability)
                          VALUES(?,?,?,?,?,?) ON CONFLICT(user_id) DO UPDATE SET address=excluded.address,age=excluded.age,
                          skills=excluded.skills,interests=excluded.interests,availability=excluded.availability""",
                       (uid,request.form.get("address"),request.form.get("age") or None,
                        request.form.get("skills"),request.form.get("interests"),request.form.get("availability")))
        db.commit(); session["name"]=request.form.get("name","").strip()
        flash("Profile updated successfully.","success")
        return redirect(url_for("profile"))
    return render_template("profile.html",user=user,profile=profile)

@app.route("/volunteers")
@roles_required("admin")
def volunteers():
    q=request.args.get("q","").strip(); status=request.args.get("status","")
    sql="""SELECT u.*,p.skills,p.interests,p.availability FROM users u LEFT JOIN volunteer_profiles p ON p.user_id=u.id
           WHERE u.role='volunteer'"""
    params=[]
    if q:
        sql+=" AND (u.name LIKE ? OR u.email LIKE ? OR p.skills LIKE ?)"; params += [f"%{q}%"]*3
    if status:
        sql+=" AND u.status=?"; params.append(status)
    sql+=" ORDER BY u.created_at DESC"
    rows=get_db().execute(sql,params).fetchall()
    return render_template("volunteers.html",volunteers=rows,q=q,status=status)

@app.route("/volunteers/<int:user_id>/status", methods=["POST"])
@roles_required("admin")
def volunteer_status(user_id):
    status=request.form.get("status")
    if status not in ("approved","rejected","disabled"): return "Invalid status",400
    db=get_db(); db.execute("UPDATE users SET status=? WHERE id=? AND role='volunteer'",(status,user_id)); db.commit()
    notify(user_id, f"Your volunteer account status is now: {status}.")
    flash("Volunteer status updated.","success")
    return redirect(url_for("volunteers"))

@app.route("/events")
@login_required
def events():
    db=get_db()
    rows=db.execute("""SELECT e.*,u.name coordinator,
       (SELECT COUNT(*) FROM registrations r WHERE r.event_id=e.id AND r.status='approved') registered
       FROM events e LEFT JOIN users u ON u.id=e.coordinator_id
       WHERE e.status!='cancelled' ORDER BY e.event_date""").fetchall()
    myregs={}
    if session["role"]=="volunteer":
        myregs={r["event_id"]:r["status"] for r in db.execute("SELECT event_id,status FROM registrations WHERE volunteer_id=?",(session["user_id"],)).fetchall()}
    coordinators=db.execute("SELECT id,name FROM users WHERE role='coordinator' AND status='approved'").fetchall()
    return render_template("events.html",events=rows,myregs=myregs,coordinators=coordinators)

@app.route("/events/create", methods=["GET","POST"])
@roles_required("admin")
def event_create():
    db=get_db()
    if request.method=="POST":
        data=[request.form.get(k) for k in ["title","description","category","event_date","start_time","end_time","venue"]]
        capacity=request.form.get("capacity",20)
        try: capacity=max(1,int(capacity))
        except: capacity=20
        db.execute("""INSERT INTO events(title,description,category,event_date,start_time,end_time,venue,capacity,required_skills,registration_deadline,coordinator_id,status)
                      VALUES(?,?,?,?,?,?,?,?,?,?,?,'upcoming')""",
                   (*data,capacity,request.form.get("required_skills"),request.form.get("registration_deadline") or data[3],
                    request.form.get("coordinator_id") or None))
        db.commit()
        for u in db.execute("SELECT id FROM users WHERE role='volunteer' AND status='approved'").fetchall():
            notify(u["id"],"A new event has been published: "+data[0])
        flash("Event created and volunteers notified.","success")
        return redirect(url_for("events"))
    coordinators=db.execute("SELECT id,name FROM users WHERE role='coordinator' AND status='approved'").fetchall()
    return render_template("event_form.html",event=None,coordinators=coordinators)

@app.route("/events/<int:event_id>/edit", methods=["GET","POST"])
@roles_required("admin")
def event_edit(event_id):
    db=get_db(); event=db.execute("SELECT * FROM events WHERE id=?",(event_id,)).fetchone()
    if not event: return "Event not found",404
    if request.method=="POST":
        db.execute("""UPDATE events SET title=?,description=?,category=?,event_date=?,start_time=?,end_time=?,venue=?,capacity=?,
                      required_skills=?,registration_deadline=?,coordinator_id=? WHERE id=?""",
                   (request.form.get("title"),request.form.get("description"),request.form.get("category"),
                    request.form.get("event_date"),request.form.get("start_time"),request.form.get("end_time"),
                    request.form.get("venue"),max(1,int(request.form.get("capacity",20))),
                    request.form.get("required_skills"),request.form.get("registration_deadline"),
                    request.form.get("coordinator_id") or None,event_id))
        db.commit(); flash("Event updated.","success"); return redirect(url_for("events"))
    coordinators=db.execute("SELECT id,name FROM users WHERE role='coordinator' AND status='approved'").fetchall()
    return render_template("event_form.html",event=event,coordinators=coordinators)

@app.route("/events/<int:event_id>/cancel", methods=["POST"])
@roles_required("admin")
def event_cancel(event_id):
    get_db().execute("UPDATE events SET status='cancelled' WHERE id=?",(event_id,)); get_db().commit()
    flash("Event cancelled. Historical records have been preserved.","success")
    return redirect(url_for("events"))

@app.route("/events/<int:event_id>/apply", methods=["POST"])
@roles_required("volunteer")
def apply_event(event_id):
    db=get_db(); event=db.execute("SELECT * FROM events WHERE id=?",(event_id,)).fetchone()
    if not event or event["status"]=="cancelled":
        flash("This event is not available.","danger"); return redirect(url_for("events"))
    today=date.today().isoformat()
    if event["registration_deadline"] and event["registration_deadline"] < today:
        flash("The registration deadline has passed.","warning"); return redirect(url_for("events"))
    count=db.execute("SELECT COUNT(*) FROM registrations WHERE event_id=? AND status='approved'",(event_id,)).fetchone()[0]
    if count >= event["capacity"]:
        flash("This event has reached its volunteer capacity.","warning"); return redirect(url_for("events"))
    try:
        db.execute("INSERT INTO registrations(event_id,volunteer_id,status) VALUES(?,?, 'pending')",(event_id,session["user_id"]))
        db.commit(); flash("Your application has been submitted.","success")
    except sqlite3.IntegrityError:
        flash("You have already applied for this event.","info")
    return redirect(url_for("events"))

@app.route("/applications")
@roles_required("admin","coordinator")
def applications():
    db=get_db()
    sql="""SELECT r.*,u.name volunteer,u.email,e.title event_title,e.coordinator_id FROM registrations r
           JOIN users u ON u.id=r.volunteer_id JOIN events e ON e.id=r.event_id"""
    params=[]
    if session["role"]=="coordinator":
        sql+=" WHERE e.coordinator_id=?"; params.append(session["user_id"])
    sql+=" ORDER BY r.applied_at DESC"
    return render_template("applications.html",applications=db.execute(sql,params).fetchall())

@app.route("/applications/<int:reg_id>/status", methods=["POST"])
@roles_required("admin","coordinator")
def application_status(reg_id):
    db=get_db()
    reg=db.execute("""SELECT r.*,e.coordinator_id,e.capacity FROM registrations r JOIN events e ON e.id=r.event_id WHERE r.id=?""",(reg_id,)).fetchone()
    if not reg: return "Not found",404
    if session["role"]=="coordinator" and reg["coordinator_id"] != session["user_id"]: return "Forbidden",403
    status=request.form.get("status")
    if status not in ("approved","rejected"): return "Invalid status",400
    if status=="approved":
        count=db.execute("SELECT COUNT(*) FROM registrations WHERE event_id=? AND status='approved'",(reg["event_id"],)).fetchone()[0]
        if count >= reg["capacity"]:
            flash("Event capacity has been reached.","warning"); return redirect(url_for("applications"))
    db.execute("UPDATE registrations SET status=? WHERE id=?",(status,reg_id)); db.commit()
    notify(reg["volunteer_id"],"Your event application has been "+status+".")
    flash("Application updated.","success")
    return redirect(url_for("applications"))

@app.route("/attendance")
@roles_required("admin","coordinator")
def attendance():
    db=get_db()
    if session["role"]=="admin":
        rows=db.execute("""SELECT r.event_id,r.volunteer_id,u.name volunteer,e.title event_title,
                           a.status attendance_status,a.hours,a.id attendance_id
                           FROM registrations r JOIN users u ON u.id=r.volunteer_id JOIN events e ON e.id=r.event_id
                           LEFT JOIN attendance a ON a.event_id=r.event_id AND a.volunteer_id=r.volunteer_id
                           WHERE r.status='approved' ORDER BY e.event_date DESC,u.name""").fetchall()
    else:
        rows=db.execute("""SELECT r.event_id,r.volunteer_id,u.name volunteer,e.title event_title,
                           a.status attendance_status,a.hours,a.id attendance_id
                           FROM registrations r JOIN users u ON u.id=r.volunteer_id JOIN events e ON e.id=r.event_id
                           LEFT JOIN attendance a ON a.event_id=r.event_id AND a.volunteer_id=r.volunteer_id
                           WHERE r.status='approved' AND e.coordinator_id=? ORDER BY e.event_date DESC,u.name""",
                        (session["user_id"],)).fetchall()
    return render_template("attendance.html",rows=rows)

@app.route("/attendance/mark", methods=["POST"])
@roles_required("admin","coordinator")
def mark_attendance():
    db=get_db(); event_id=int(request.form["event_id"]); volunteer_id=int(request.form["volunteer_id"])
    status=request.form.get("status","present")
    try: hours=max(0,min(24,float(request.form.get("hours",0))))
    except: hours=0
    event=db.execute("SELECT coordinator_id FROM events WHERE id=?",(event_id,)).fetchone()
    if not event: return "Event not found",404
    if session["role"]=="coordinator" and event["coordinator_id"] != session["user_id"]: return "Forbidden",403
    if status not in ("present","absent","late","excused"): return "Invalid status",400
    db.execute("""INSERT INTO attendance(event_id,volunteer_id,status,hours) VALUES(?,?,?,?)
                  ON CONFLICT(event_id,volunteer_id) DO UPDATE SET status=excluded.status,hours=excluded.hours,marked_at=CURRENT_TIMESTAMP""",
               (event_id,volunteer_id,status,hours))
    db.commit(); notify(volunteer_id,f"Your attendance has been marked {status}.")
    flash("Attendance saved.","success"); return redirect(url_for("attendance"))

@app.route("/uploads/<path:filename>")
@login_required
def uploaded_file(filename):
    return send_from_directory(UPLOAD_DIR, filename, as_attachment=False)

@app.route("/my-attendance")
@roles_required("volunteer")
def my_attendance():
    rows=get_db().execute("""SELECT a.*,e.title event_title,e.event_date FROM attendance a JOIN events e ON e.id=a.event_id
                             WHERE a.volunteer_id=? ORDER BY e.event_date DESC""",(session["user_id"],)).fetchall()
    return render_template("my_attendance.html",rows=rows)

@app.route("/reports", methods=["GET","POST"])
@login_required
def reports():
    db=get_db()
    if request.method=="POST" and session["role"]=="volunteer":
        event_id=int(request.form["event_id"])
        valid=db.execute("SELECT id FROM registrations WHERE event_id=? AND volunteer_id=? AND status='approved'",
                         (event_id,session["user_id"])).fetchone()
        if not valid:
            flash("You can submit a report only for an approved event registration.","danger"); return redirect(url_for("reports"))
        attachment=None
        file=request.files.get("attachment")
        if file and file.filename:
            filename=secure_filename(file.filename)
            ext=filename.rsplit(".",1)[-1].lower() if "." in filename else ""
            if ext not in ALLOWED_EXTENSIONS:
                flash("Unsupported attachment type. Use JPG, PNG, PDF, DOC, or DOCX.","danger"); return redirect(url_for("reports"))
            os.makedirs(UPLOAD_DIR,exist_ok=True)
            safe_name=f"{session['user_id']}_{int(datetime.now().timestamp())}_{filename}"
            file.save(os.path.join(UPLOAD_DIR,safe_name)); attachment=safe_name
        try: hours=max(0,min(24,float(request.form.get("hours",0))))
        except: hours=0
        db.execute("""INSERT INTO activity_reports(event_id,volunteer_id,activities,description,hours,achievements,challenges,attachment)
                      VALUES(?,?,?,?,?,?,?,?)""",
                   (event_id,session["user_id"],request.form.get("activities"),request.form.get("description"),
                    hours,request.form.get("achievements"),request.form.get("challenges"),attachment))
        db.commit(); flash("Activity report submitted for review.","success"); return redirect(url_for("reports"))
    if session["role"]=="volunteer":
        rows=db.execute("""SELECT ar.*,e.title event_title FROM activity_reports ar JOIN events e ON e.id=ar.event_id
                           WHERE ar.volunteer_id=? ORDER BY ar.submitted_at DESC""",(session["user_id"],)).fetchall()
        eligible=db.execute("""SELECT e.id,e.title FROM registrations r JOIN events e ON e.id=r.event_id
                               WHERE r.volunteer_id=? AND r.status='approved' ORDER BY e.event_date DESC""",(session["user_id"],)).fetchall()
    elif session["role"]=="coordinator":
        rows=db.execute("""SELECT ar.*,u.name volunteer,e.title event_title,e.coordinator_id FROM activity_reports ar
                           JOIN users u ON u.id=ar.volunteer_id JOIN events e ON e.id=ar.event_id
                           WHERE e.coordinator_id=? ORDER BY ar.submitted_at DESC""",(session["user_id"],)).fetchall(); eligible=[]
    else:
        rows=db.execute("""SELECT ar.*,u.name volunteer,e.title event_title FROM activity_reports ar
                           JOIN users u ON u.id=ar.volunteer_id JOIN events e ON e.id=ar.event_id
                           ORDER BY ar.submitted_at DESC""").fetchall(); eligible=[]
    return render_template("reports.html",reports=rows,eligible=eligible)

@app.route("/reports/<int:report_id>/review", methods=["POST"])
@roles_required("admin","coordinator")
def review_report(report_id):
    db=get_db()
    row=db.execute("""SELECT ar.*,e.coordinator_id FROM activity_reports ar JOIN events e ON e.id=ar.event_id WHERE ar.id=?""",(report_id,)).fetchone()
    if not row: return "Not found",404
    if session["role"]=="coordinator" and row["coordinator_id"] != session["user_id"]: return "Forbidden",403
    status=request.form.get("status")
    if status not in ("approved","revision_requested","rejected"): return "Invalid status",400
    db.execute("UPDATE activity_reports SET status=?,coordinator_feedback=? WHERE id=?",
               (status,request.form.get("feedback"),report_id)); db.commit()
    notify(row["volunteer_id"],"Your activity report status: "+status)
    flash("Report review saved.","success"); return redirect(url_for("reports"))

@app.route("/announcements", methods=["GET","POST"])
@login_required
def announcements():
    db=get_db()
    if request.method=="POST" and session["role"]=="admin":
        title=request.form.get("title","").strip(); message=request.form.get("message","").strip()
        if title and message:
            db.execute("INSERT INTO announcements(title,message) VALUES(?,?)",(title,message))
            for u in db.execute("SELECT id FROM users WHERE status='approved'").fetchall():
                notify(u["id"],"New announcement: "+title)
            db.commit(); flash("Announcement published.","success")
        return redirect(url_for("announcements"))
    rows=db.execute("SELECT * FROM announcements ORDER BY created_at DESC").fetchall()
    return render_template("announcements.html",announcements=rows)

@app.route("/notifications")
@login_required
def notifications():
    db=get_db()
    db.execute("UPDATE notifications SET is_read=1 WHERE user_id=?",(session["user_id"],)); db.commit()
    rows=db.execute("SELECT * FROM notifications WHERE user_id=? ORDER BY created_at DESC",(session["user_id"],)).fetchall()
    return render_template("notifications.html",notifications=rows)

@app.route("/export/volunteers.csv")
@roles_required("admin")
def export_volunteers():
    rows=get_db().execute("SELECT name,email,phone,status,created_at FROM users WHERE role='volunteer' ORDER BY name").fetchall()
    out=io.StringIO(); writer=csv.writer(out); writer.writerow(["Name","Email","Phone","Status","Registered At"])
    writer.writerows([tuple(r) for r in rows])
    return Response(out.getvalue(),mimetype="text/csv",headers={"Content-Disposition":"attachment; filename=volunteers.csv"})

@app.route("/export/attendance.csv")
@roles_required("admin","coordinator")
def export_attendance():
    sql="""SELECT e.title,u.name,a.status,a.hours,a.marked_at FROM attendance a JOIN events e ON e.id=a.event_id
           JOIN users u ON u.id=a.volunteer_id"""
    params=[]
    if session["role"]=="coordinator":
        sql+=" WHERE e.coordinator_id=?"; params.append(session["user_id"])
    rows=get_db().execute(sql+" ORDER BY e.event_date DESC",params).fetchall()
    out=io.StringIO(); writer=csv.writer(out); writer.writerow(["Event","Volunteer","Status","Hours","Marked At"])
    writer.writerows([tuple(r) for r in rows])
    return Response(out.getvalue(),mimetype="text/csv",headers={"Content-Disposition":"attachment; filename=attendance.csv"})

@app.errorhandler(413)
def too_large(e):
    flash("File is too large. Maximum upload size is 8 MB.","danger")
    return redirect(request.referrer or url_for("dashboard"))

@app.errorhandler(404)
def not_found(e):
    return render_template("error.html",code=404,message="The page you requested could not be found."),404

@app.errorhandler(500)
def server_error(e):
    return render_template("error.html",code=500,message="Something went wrong. Please try again."),500

if __name__ == "__main__":
    os.makedirs(UPLOAD_DIR,exist_ok=True)
    init_db()
    app.run(debug=True, host="127.0.0.1", port=5000)
