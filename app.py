from flask import Flask, render_template, request, jsonify, redirect, url_for, flash
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from rdflib import Graph, Namespace, RDF, URIRef, Literal, XSD
import os
from config import Config

app = Flask(__name__)
app.config.from_object(Config)

# Ensure instance folder exists
os.makedirs(os.path.join(app.root_path, 'instance'), exist_ok=True)

# Init extensions
db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'

# === Load Ontology ===
ONTOLOGY = Graph()
ONTOLOGY.parse(Config.ONTOLOGY_PATH, format="xml")  # or "turtle"


def infer_base_iri(graph: Graph) -> str:
    """
    Try to recover the ontology base IRI from namespace bindings first, then fall back
    to the graph identifier, and finally to a sensible default. Ensures the result
    always ends with '#'.
    """
    for prefix, uri in graph.namespaces():
        if prefix in ("", None, "math-addition"):
            iri = str(uri)
            return iri if iri.endswith("#") else iri + "#"

    iri = str(graph.identifier) if getattr(graph, "identifier", None) else ""
    if iri:
        return iri if iri.endswith("#") else iri + "#"

    return "http://www.semanticweb.org/nitesh/ontologies/2025/11/math-addition#"


# Extract base IRI and namespace
ONTO_IRI = infer_base_iri(ONTOLOGY)
MATH = Namespace(ONTO_IRI)

print(f"✅ Ontology loaded from {Config.ONTOLOGY_PATH}")
print(f"   Base IRI: {ONTO_IRI}")

# Verify key terms exist
required_classes = ['Number', 'AdditionExpression']
required_props = ['hasAdded', 'hasResult', 'hasValue']

for cls in required_classes:
    if (MATH[cls], None, None) not in ONTOLOGY:
        print(f"⚠️ Warning: Class {cls} not found in ontology")

for prop in required_props:
    if (MATH[prop], None, None) not in ONTOLOGY:
        print(f"⚠️ Warning: Property {prop} not found in ontology")

# === Database Models ===
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(128), nullable=False)
    attempts = db.relationship('Attempt', backref='user', lazy=True)

class Attempt(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    a = db.Column(db.Integer, nullable=False)
    b = db.Column(db.Integer, nullable=False)
    student_answer = db.Column(db.Integer, nullable=False)
    correct_answer = db.Column(db.Integer, nullable=False)
    is_correct = db.Column(db.Boolean, nullable=False)
    timestamp = db.Column(db.DateTime, default=db.func.current_timestamp())

# === User Loader ===
@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# === Routes ===
@app.route('/')
@login_required
def home():
    import random
    a = random.randint(0, 10)
    b = random.randint(0, 10)
    return render_template('index.html', a=a, b=b)


@app.route('/dashboard')
@login_required
def dashboard():
    page = request.args.get('page', 1, type=int)
    per_page = 10
    pagination = (
        Attempt.query.filter_by(user_id=current_user.id)
        .order_by(Attempt.timestamp.desc())
        .paginate(page=page, per_page=per_page, error_out=False)
    )
    return render_template(
        'dashboard.html',
        attempts=pagination.items,
        pagination=pagination,
    )

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        if User.query.filter_by(email=email).first():
            flash('Email already registered')
            return redirect(url_for('register'))
        user = User(email=email, password_hash=generate_password_hash(password))
        db.session.add(user)
        db.session.commit()
        login_user(user)
        return redirect(url_for('home'))
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        user = User.query.filter_by(email=email).first()
        if user and check_password_hash(user.password_hash, password):
            login_user(user)
            return redirect(url_for('home'))
        flash('Invalid email or password')
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

@app.route('/check', methods=['POST'])
@login_required
def check_answer():
    a = int(request.form['a'])
    b = int(request.form['b'])
    student_ans = int(request.form['answer'])
    correct = a + b
    is_correct = (student_ans == correct)

    # Save to DB
    attempt = Attempt(
        user_id=current_user.id,
        a=a, b=b,
        student_answer=student_ans,
        correct_answer=correct,
        is_correct=is_correct
    )
    db.session.add(attempt)
    db.session.commit()

    # Optional: Generate OWL-style Turtle for this attempt
    g = Graph()
    g.bind("math", MATH)

    # Create instance URIs (you can use attempt.id for uniqueness)
    expr = MATH[f"Expr_{attempt.id}"]
    num_a = MATH[f"Num_{a}_{attempt.id}"]
    num_b = MATH[f"Num_{b}_{attempt.id}"]
    num_res = MATH[f"Num_{student_ans}_{attempt.id}"]

    # Use classes/properties from YOUR ontology
    g.add((expr, RDF.type, MATH.AdditionExpression))
    g.add((expr, MATH.hasAdded, num_a))
    g.add((expr, MATH.hasAdded, num_b))
    g.add((expr, MATH.hasResult, num_res))

    g.add((num_a, RDF.type, MATH.Number))
    g.add((num_b, RDF.type, MATH.Number))
    g.add((num_res, RDF.type, MATH.Number))

    g.add((num_a, MATH.hasValue, Literal(a, datatype=XSD.integer)))
    g.add((num_b, MATH.hasValue, Literal(b, datatype=XSD.integer)))
    g.add((num_res, MATH.hasValue, Literal(student_ans, datatype=XSD.integer)))

    print("\n--- Student Attempt (OWL/Turtle) ---")
    print(g.serialize(format="turtle"))

    return jsonify({
        'correct': is_correct,
        'answer': correct,
        'message': f"✅ Correct! {a} + {b} = {correct}" if is_correct else f"❌ Try again. {a} + {b} = {correct}"
    })

# === Create DB on first run ===
with app.app_context():
    db.create_all()

if __name__ == '__main__':
    app.run(debug=True)