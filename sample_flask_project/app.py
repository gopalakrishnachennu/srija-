from flask import Flask, flash, redirect, render_template, request, session, url_for


USERS = {"admin": "admin123"}


def create_app(test_config=None):
    app = Flask(__name__)
    app.config.from_mapping(SECRET_KEY="demo-secret-change-me")
    if test_config:
        app.config.update(test_config)

    @app.route("/")
    def home():
        return redirect(url_for("dashboard" if session.get("user") else "login"))

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if session.get("user"):
            return redirect(url_for("dashboard"))

        error = None
        if request.method == "POST":
            username = request.form.get("username", "").strip()
            password = request.form.get("password", "")
            if not username or not password:
                error = "Username and password are required"
            elif USERS.get(username) != password:
                error = "Invalid username or password"
            else:
                session.clear()
                session["user"] = username
                flash("Welcome back! You signed in successfully.", "success")
                return redirect(url_for("dashboard"))
        return render_template("login.html", error=error)

    @app.route("/dashboard")
    def dashboard():
        if not session.get("user"):
            flash("Please sign in to view the dashboard.", "warning")
            return redirect(url_for("login"))
        return render_template("dashboard.html", username=session["user"])

    @app.post("/logout")
    def logout():
        session.clear()
        flash("You have been signed out.", "success")
        return redirect(url_for("login"))

    return app


app = create_app()


if __name__ == "__main__":
    app.run(debug=True, port=5001)
