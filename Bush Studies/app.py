# File: app.py
# Versions: Python 3.7, Flask 1.0.2, SQLAlchemy 1.2.10, TinyMCE 5.0.6, etc.
# Name: Sivan Cooperman
# Date: 5.23.2019
# Desc: The main code to run the Bush Studies Website

# The Flask Library/Framework provides the main code for actually connecting to
# the database and making sure the website runs. SQLAlchemy is the interface
# between Flask and the MySQL database.
from flask import Flask, render_template, request, redirect, url_for
from flask import session as flasksession
from flask_oauth import OAuth
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# random library for creating unique identifiers for each study and each
# database entry ( the `primary_key` for each instance of a class in the db has
# to be unique )
# json library for parsing account login info
# sys for printing to the error log
from random import SystemRandom
import json
import sys

# For having a rich text editor and more robust form for the creation page.
# TinyMCE natively only works with JS, but through the python wtf_tinymce
# library I got it to work with Flask.
# (FUTURE: Switch all forms over to wtforms?)
from wtf_tinymce import wtf_tinymce
from wtf_tinymce.forms.fields import TinyMceField
from wtforms import Form, StringField, validators

# Handling errors from the server and such.
from urllib.request import Request, urlopen
from urllib.error import URLError

# Instantiating the App
app = Flask(__name__)

# Associating the app with the database ( databasetype://username:password@databaselocation/username$databasename )
app.config['SQLALCHEMY_DATABASE_URI'] = 'mysql://bushstudies:JtCLk4i2wNfifVJ@bushstudies.mysql.pythonanywhere-services.com/bushstudies$default'

# Instantiating the database as db and doing something(?) with tinymce
wtf_tinymce.init_app(app)
db = SQLAlchemy(app)
db.init_app(app)

# The pool_recycle parameter is used because the pythonanywhere server
# terminates open connections every five minutes, and you'll get an error
# otherwise if a connection is left open for longer than five minutes.
engine = create_engine('mysql://bushstudies:JtCLk4i2wNfifVJ@bushstudies.mysql.pythonanywhere-services.com/bushstudies$default', pool_recycle=280)

# Creating the Session class. The Session is used as a way to make changes
# to the database.
Session = sessionmaker(bind=engine)

# Google authentification, copied from
# https://pythonspot.com/login-to-flask-app-with-google/
# ( FUTURE: Move security stuff off my account? )
GOOGLE_CLIENT_ID = '17388497476-7q73d8mtq2l5gu5c51fgrbssbd9tfphg.apps.googleusercontent.com'
GOOGLE_CLIENT_SECRET = 'xkV_UotQnzMabWi_zM4A4pr_'
REDIRECT_URI = '/oauth2callback'
SECRET_KEY = 'helenbush'
DEBUG = True
app.debug = DEBUG
app.secret_key = SECRET_KEY
oauth = OAuth()
google = oauth.remote_app('google',
base_url='https://www.google.com/accounts/',
authorize_url='https://accounts.google.com/o/oauth2/auth',
request_token_url=None,
request_token_params={'scope': 'https://www.googleapis.com/auth/userinfo.email',
'response_type': 'code'},
access_token_url='https://accounts.google.com/o/oauth2/token',
access_token_method='POST',
access_token_params={'grant_type': 'authorization_code'},
consumer_key=GOOGLE_CLIENT_ID,
consumer_secret=GOOGLE_CLIENT_SECRET)

# Here, classes are defined that will be stored in the database. I believe
# any modifications to the structure of a class (but not the addition or
# subtraction of classes) require the database to be
# deleted and remade, deleting all studies, so be careful.
# ( FUTURE: take a look at python alembic for database migration. )

# The base of the study; tracks the owner email, title, author, and its id.
# Also points to collections of text or images associated with the study's main
# body. See https://flask-sqlalchemy.palletsprojects.com/en/2.x/models/ and
# https://docs.sqlalchemy.org/en/13/orm/basic_relationships.html
class Study(db.Model):

    __tablename__ = 'study'

    study_id = db.Column(db.Integer, primary_key=True)
    owner_id = db.Column(db.String(40))
    title = db.Column(db.String(200))
    author = db.Column(db.String(100))
    texts = db.relationship('Text', backref='study', lazy='joined')
    urls = db.relationship('Image', backref='study', lazy='joined')

# A Text object; tracks its contents and an id shared with its corresponding
# Study and Image objects to be reassembled when needed, as well as its position
# in the study.
class Text(db.Model):

    __tablename__ = 'text'

    unique_id = db.Column(db.Integer, primary_key=True)
    text = db.Column(db.Text)
    order = db.Column(db.Integer)
    study_id = db.Column(db.Integer, db.ForeignKey('study.study_id'), nullable=False)

# Similar to a Text object, but keeps a url to a hosted image instead.
# (FUTURE: space to host images locally? WTForms could support file upload.)
class Image(db.Model):

    __tablename__ = 'image'

    unique_id = db.Column(db.Integer, primary_key=True)
    url = db.Column(db.String(200))
    order = db.Column(db.Integer)
    study_id = db.Column(db.Integer, db.ForeignKey('study.study_id'), nullable=False)

# The form we'll use for our creation page. This is not added to the database.
class TextForm(Form):
    title = StringField('Title', [validators.InputRequired()])
    author = StringField('Author', [validators.InputRequired()])
    text = TinyMceField('Text')
    img = StringField('Image URL', [validators.InputRequired(), validators.URL()])

# Instantiates all the db.model classes in the database
db.create_all()

# I use global variables (demarcated by all caps variable names), to pass
# values between pages for the most part.

# The user's email address
ACCOUNT_ID = ''
# Anyone on this list will be able to delete any study, regardless of ownership;
# Currently just myself and the department chairs.
ADMINS = ['sivan.cooperman@bush.edu', 'laura.leblanc@bush.edu', 'paula.dowtin@bush.edu', 'christine.miller@bush.edu',
'chelsea.jennings@bush.edu', 'grace.hayek@bush.edu', 'sarah.kennedy@bush.edu']
# Anyone on this list will be able to view the site, but not post studies.
BANNED = []
# Used in construction of the study
ELEMENTS = []
NEWSTUDY = 1

# The '@' symbol denotes a decorator ( http://book.pythontips.com/en/latest/decorators.html#writing-your-first-decorator ).
# What's important is the form @app.route('/subpath'); the function below it
# will be run when accessing that subpath on the website.
@app.route('/')
def index():
    # In order to modify a global variable, use the global prefix to
    # instantiate it in your function
    global ACCOUNT_ID
    global ADMINS

    # Checking if the user is authenticated; don't confuse flask.flasksession and
    # Session = sqlalchemy.orm.sessionmaker!
    access_token = flasksession.get('access_token')
    if access_token is None:
        return redirect(url_for('login'))

    # No clue what this does
    access_token = access_token[0]

    # Authenticates and checks for bad login??
    headers = {'Authorization': 'OAuth '+access_token}
    req = Request('https://www.googleapis.com/oauth2/v1/userinfo',
    None, headers)
    try:
        res = urlopen(req)
    except URLError as e:
        if e.code == 401:
            # Unauthorized - bad token
            flasksession.pop('access_token', None)
            return redirect(url_for('login'))
        return res.read()

    # res.read() returns the JSON data of the person logging in; print it out
    # (or anything) with print(yourthing, file=sys.stderr), and then view it
    # in the pythonanywhere error log.
    json_data = res.read()
    json_data = json.loads(json_data)
    ACCOUNT_ID = json_data['email']

    # If an account is not a bush account, send them to the denied page and
    # revoke their access token.
    if ACCOUNT_ID.split('@')[1] != 'bush.edu':
        flasksession.pop('access_token', None)
        return render_template('denied.html')

    # Returning the results of the render_template function tells flask to bring
    # up the html at that file location when accessing this subpath.
    return render_template('index.html')

# The following 3 functions are all from the flask auth website again.
@app.route('/login')
def login():
    callback=url_for('authorized', _external=True)
    return google.authorize(callback=callback)

@app.route(REDIRECT_URI)
@google.authorized_handler
def authorized(resp):
    access_token = resp['access_token']
    flasksession['access_token'] = access_token, ''
    return redirect(url_for('index'))

@google.tokengetter
def get_access_token():
    return flasksession.get('access_token')

# The page upon which all the studies are displayed at once. The `methods`
# argument tells you what kinds of ways the page can be accessed, either by
# getting information from it or posting information to it. You'll get a 405
# error sometimes without it.
@app.route('/studies/', methods=['GET'])
def studies(study_id=None):
    # Checking for a token
    access_token = flasksession.get('access_token')
    if access_token is None:
        return redirect(url_for('login'))

    # Opening an SQLAlchemy session; once you open a session, you can make
    # changes, then commit the changes with session.commit() and then close it
    # with session.close()
    session = Session()

    # Making sure our list of studies is not empty. If there are no entries,
    # first() returns None. session.query is the way to query the database
    # for specific objects.
    if session.query(Study).first():
        # Compiling a list of titles, ids, and authors to be sent to the html
        studies = [study for study in session.query(Study)]

        session.close()

    # "If our list of studies is empty..."
    else:
        studies = []
        session.close()

    # Passing a variable to the html so it can use it
    return render_template('studies.html', studies=studies)

# Note the usage of the '/subpath/<var>' in the decorator
# ( http://flask.pocoo.org/docs/1.0/quickstart/#routing ).
# Make sure to include the argument in the function parameters too.
@app.route('/studies/<study_id>', methods=['GET', 'POST'])
def display_study(study_id):
    access_token = flasksession.get('access_token')
    if access_token is None:
        return redirect(url_for('login'))

    session = Session()

    # Here using a query to look for a particular set of studies. There should
    # only be one Study object returned, and study.texts and study.urls should
    # point to all text or image objects with the same study_id.
    study = session.query(Study).filter(Study.study_id == study_id).first()

    session.close()

    return render_template('studies.html', uid=study_id,
    study=study, account_id=ACCOUNT_ID, admins=ADMINS)

@app.route('/create', methods=['GET', 'POST'])
def create():
    access_token = flasksession.get('access_token')
    if access_token is None:
        return redirect(url_for('login'))
    # Not much here because the posting is being handled by the redirect URL
    # ( search for 'post redirect get' to get an idea of why we redirect ).
    # You can also see why global variables are so helpful here.
    form = TextForm()

    return render_template('create.html', elements=ELEMENTS, newStudy=NEWSTUDY,
    form=form, account_id=ACCOUNT_ID, banned=BANNED)

@app.route('/search/<title>', methods=['GET'])
def search(title):
    access_token = flasksession.get('access_token')
    if access_token is None:
        return redirect(url_for('login'))

    session = Session()

    results = session.query(Study).filter(Study.title == title).all()

    session.close()

    return render_template('search.html', results=results, title=title)

@app.route('/about')
def about():
    access_token = flasksession.get('access_token')
    if access_token is None:
        return redirect(url_for('login'))

    return render_template('about.html')

@app.route('/admin')
def admin():
    access_token = flasksession.get('access_token')
    if access_token is None:
        return redirect(url_for('login'))

    if ACCOUNT_ID not in ADMINS:
        return redirect(url_for('index'))
    else:
        return render_template('admin.html')

# The route that makes it so we don't double submit forms on refresh,
# by using a redirector function in between posting data and getting its
# display.
@app.route('/redirect/<page>', methods=['POST'])
def redirector(page):
    session = Session()
    global ELEMENTS

    if page == 'studies':
        # I think this is the best way to check what request is sent, but I
        # could be wrong; request.form only appears to work when using an <input>
        # element and giving it a name attribute and type='submit'.
        if 'submitstudy' in list(request.form.keys()):
            # Generating a unique identifier for our new study that just got posted
            rng = SystemRandom()
            study_id = int(rng.random()*10**8)
            # Making sure it's not taken (although incredibly unlikely)
            while session.query(Study).filter(Study.study_id==study_id).first():
                study_id = int(SystemRandom().random()*10**8)

            # Creating our study object without the pointers.
            study = Study(study_id=study_id, owner_id=ACCOUNT_ID, title=request.form['title'], author=request.form['author'])

            # Counters to know which element of the request.form.getlist() to
            # take. request.form.getlist(arg) returns a list of all submissions
            # with that name, which is useful here when we have multiple 'text'
            # and 'img' form submissions.
            textCounter = 0
            imgCounter = 0

            # Adding everything to the databse in order per ELEMENTS
            for element in ELEMENTS:
                if element == 't':
                    words = Text(unique_id=int(rng.random()*10**8), text=request.form.getlist('text')[textCounter], order=textCounter+imgCounter, study_id=study_id)
                    textCounter += 1
                    # Creating a link between the object and the study object
                    study.texts.append(words)
                    session.add(words)
                elif element == 'i':
                    image = Image(unique_id=int(rng.random()*10**8), url=request.form.getlist('img')[imgCounter], order=textCounter+imgCounter, study_id=study_id)
                    imgCounter += 1
                    study.urls.append(image)
                    session.add(image)

            # May be necessary to add the "many" objects to session before the
            # "one"
            session.add(study)

            # Clearing the elements list for the next study creation
            ELEMENTS = []

        # "If we're deleting and not posting..."
        elif list(request.form.keys())[0].startswith('deletestudy'):
            # Getting the study id in a really stupid way by passing it in
            # as part of the button name
            delete_id = int(list(request.form.keys())[0].split('y')[1])
            # Deleting every object that has the study_id
            for text in session.query(Study).filter(Study.study_id == delete_id).first().texts:
                session.delete(text)
            for image in session.query(Study).filter(Study.study_id == delete_id).first().urls:
                session.delete(image)
            session.delete(session.query(Study).filter(Study.study_id == delete_id).first())

    elif page == 'create':
        global NEWSTUDY
        if 'clear' in list(request.form.keys()):
            ELEMENTS = []
        else:
            # In order to keep track of the order in which the elements exist while
            # in creation mode, I created a global variable. Note that global variables
            # are wiped when the website is reloaded (from the server side, not F5)
            # BUG: Adding an element will wipe the content from all current cells.
            # FUTURE: Is there a better way to do this? Can objects be created and
            # kept track of instead of element list?
            keys = list(request.form.keys())
            if 'addtextnew' in keys:
                ELEMENTS = []
                ELEMENTS.append('t')
            elif 'addimgnew' in keys:
                ELEMENTS = []
                ELEMENTS.append('i')
            elif 'addtext' in keys:
                ELEMENTS.append('t')
            elif 'addimg' in keys:
                ELEMENTS.append('i')
            NEWSTUDY = 0

    elif page == 'search':
        title = request.form['title']

        # Special ending for search because we need to return something different
        # because I didn't want to use a global variable for a searched title.
        return redirect(url_for('search', title=title))

    # Secret admin page for bans, unbans, and admin privileges. IMPORTANT: if
    # you reload the page on the server side, all non-hardcoded bans and admins will
    # be lost.
    # ( FUTURE: Add an object to the database that holds all this? )
    elif page == 'admin':
        if ACCOUNT_ID in ADMINS:
            if request.form['addadmin'] != '':
                ADMINS.append(request.form['addadmin'])
            if request.form['ban'] != '':
                BANNED.append(request.form['ban'])
            if request.form['unban'] != '':
                try:
                    del BANNED[BANNED.index(request.form['unban'])]
                except:
                    pass
        else:
            return redirect(url_for('index'))

    # Committing our changes to the database.
    session.commit()
    session.close()

    # Whichever page we wanted to post to, take us there.
    return redirect(url_for(page))

# Running the code at the end
def main():
    app.run()
if __name__ == '__main__':
    main()