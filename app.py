from flask import Flask, render_template, request, redirect, url_for, session, flash, abort
from flask_sqlalchemy import SQLAlchemy
from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, SubmitField, TextAreaField, FileField, MultipleFileField
from wtforms.validators import DataRequired, Length, EqualTo
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import os, uuid, shutil

app = Flask(__name__)
app.secret_key = "replace_this_with_a_random_secret_key"

# Directory setup
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
PROFILE_FOLDER = os.path.join(BASE_DIR, 'static', 'uploads', 'profiles')
POST_FOLDER = os.path.join(BASE_DIR, 'static', 'uploads', 'posts')
os.makedirs(PROFILE_FOLDER, exist_ok=True)
os.makedirs(POST_FOLDER, exist_ok=True)
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}

app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///" + os.path.join(BASE_DIR, "blog.db")
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config['UPLOAD_FOLDER_PROFILE'] = PROFILE_FOLDER
app.config['UPLOAD_FOLDER_POST'] = POST_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 10 * 1024 * 1024  # 10MB max

db = SQLAlchemy(app)

# Models
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(32), unique=True, nullable=False)
    password_hash = db.Column(db.String(128), nullable=False)
    display_name = db.Column(db.String(64), nullable=False)
    bio = db.Column(db.String(300), default="")
    profile_picture = db.Column(db.String(128), nullable=True)
    posts = db.relationship("Post", backref="author", lazy=True)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)
    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

class Post(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(100), nullable=False)
    content = db.Column(db.Text, nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    images = db.relationship("PostImage", backref="post", cascade="all, delete", lazy=True)

class PostImage(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    filename = db.Column(db.String(128), nullable=False)
    post_id = db.Column(db.Integer, db.ForeignKey('post.id'), nullable=False)

# Forms
class RegisterForm(FlaskForm):
    username = StringField("Username", validators=[DataRequired(), Length(min=3,max=32)])
    display_name = StringField("Display Name", validators=[DataRequired(), Length(min=2,max=64)])
    password = PasswordField("Password", validators=[DataRequired(), Length(min=4)])
    confirm = PasswordField("Confirm Password", validators=[DataRequired(), EqualTo('password', message='Passwords must match')])
    submit = SubmitField("Register")

class LoginForm(FlaskForm):
    username = StringField("Username", validators=[DataRequired()])
    password = PasswordField("Password", validators=[DataRequired()])
    submit = SubmitField("Login")

class EditProfileForm(FlaskForm):
    display_name = StringField("Display Name", validators=[DataRequired(), Length(min=2,max=64)])
    bio = TextAreaField("Bio", validators=[Length(max=300)])
    profile_picture = FileField("Profile Picture (optional)")
    remove_picture = SubmitField("Remove Profile Picture")
    submit = SubmitField("Update Profile")

class PostForm(FlaskForm):
    title = StringField("Title", validators=[DataRequired(), Length(max=100)])
    content = TextAreaField("Content", validators=[DataRequired()])
    images = MultipleFileField("Upload Images (you can select multiple!)")
    submit = SubmitField("Add Post")

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# Create tables if they don't exist
with app.app_context():
    db.create_all()

def get_current_user():
    if "user_id" in session:
        return User.query.get(session["user_id"])
    return None

def save_profile_picture(file, username):
    if file and allowed_file(file.filename):
        ext = file.filename.rsplit('.', 1)[1].lower()
        filename = f"{username}_{uuid.uuid4().hex[:10]}.{ext}"
        file.save(os.path.join(PROFILE_FOLDER, filename))
        return filename
    return None

def save_post_images(files, username):
    filenames = []
    for file in files:
        if file and allowed_file(file.filename):
            ext = file.filename.rsplit('.', 1)[1].lower()
            filename = f"{username}_{uuid.uuid4().hex[:10]}.{ext}"
            file.save(os.path.join(POST_FOLDER, filename))
            filenames.append(filename)
    return filenames

@app.route("/", methods=["GET", "POST"])
def home():
    posts = Post.query.order_by(Post.id.desc()).all()
    user = get_current_user()
    form = PostForm()
    if user and form.validate_on_submit():
        new_post = Post(
            title=form.title.data,
            content=form.content.data,
            author=user
        )
        db.session.add(new_post)
        db.session.commit()  # Commit now to get Post ID for image relations

        files = request.files.getlist("images")
        filenames = save_post_images(files, user.username)
        for fname in filenames:
            db.session.add(PostImage(filename=fname, post=new_post))
        db.session.commit()
        flash("Post added!", "success")
        return redirect(url_for('home'))
    return render_template("home.html", posts=posts, user=user, form=form)

@app.route("/post/<int:post_id>", methods=["GET", "POST"])
def post_detail(post_id):
    post = Post.query.get_or_404(post_id)
    user = get_current_user()
    if request.method == "POST" and user and post.author.id == user.id:
        # Delete images
        delete_ids = request.form.getlist("delete_image")
        for img_id in delete_ids:
            img = PostImage.query.get(img_id)
            if img and img in post.images:
                img_path = os.path.join(POST_FOLDER, img.filename)
                if os.path.exists(img_path):
                    os.remove(img_path)
                db.session.delete(img)
        db.session.commit()
        flash("Image(s) deleted.", "success")
        return redirect(url_for("post_detail", post_id=post.id))
    return render_template("post_detail.html", post=post, user=user)

@app.route("/register", methods=["GET","POST"])
def register():
    form = RegisterForm()
    if form.validate_on_submit():
        if User.query.filter_by(username=form.username.data).first():
            flash("Username already exists.", "danger")
        else:
            user = User(username=form.username.data, display_name=form.display_name.data)
            user.set_password(form.password.data)
            db.session.add(user)
            db.session.commit()
            flash("Registration successful! Please log in.", "success")
            return redirect(url_for('login'))
    return render_template("register.html", form=form, user=get_current_user())

@app.route("/login", methods=["GET", "POST"])
def login():
    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(username=form.username.data).first()
        if user and user.check_password(form.password.data):
            session['user_id'] = user.id
            flash("Logged in successfully!", "success")
            return redirect(url_for("home"))
        else:
            flash("Incorrect credentials.", "danger")
    return render_template("login.html", form=form, user=get_current_user())

@app.route("/logout")
def logout():
    session.pop("user_id", None)
    flash("Logged out.", "info")
    return redirect(url_for("home"))

@app.route("/user/<username>")
def profile(username):
    user_obj = User.query.filter_by(username=username).first_or_404()
    return render_template("profile.html", profile_user=user_obj, user=get_current_user())

@app.route("/edit-profile", methods=["GET", "POST"])
def edit_profile():
    user = get_current_user()
    if not user:
        abort(401)
    form = EditProfileForm(obj=user)
    if form.validate_on_submit():
        user.display_name = form.display_name.data
        user.bio = form.bio.data
        # Remove profile pic
        if form.remove_picture.data:
            if user.profile_picture:
                pic_path = os.path.join(PROFILE_FOLDER, user.profile_picture)
                if os.path.exists(pic_path):
                    os.remove(pic_path)
                user.profile_picture = None
        # Upload new profile pic
        file = form.profile_picture.data
        if file and allowed_file(file.filename):
            if user.profile_picture:
                # Remove old
                old_path = os.path.join(PROFILE_FOLDER, user.profile_picture)
                if os.path.exists(old_path):
                    os.remove(old_path)
            filename = save_profile_picture(file, user.username)
            user.profile_picture = filename
        db.session.commit()
        flash("Profile updated.", "success")
        return redirect(url_for("profile", username=user.username))
    return render_template("edit_profile.html", form=form, user=user)

if __name__ == "__main__":
    app.run(debug=True)
