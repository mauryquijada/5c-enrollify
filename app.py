import time
import requests
from flask import Flask, render_template, request, make_response
import json
import sqlite3
import re
from flask_errormail import mail_on_500
from random import randint

from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import smtplib

app = Flask(__name__)
app.config.from_pyfile('app.cfg', silent=True)

FROM_EMAIL = app.config["FROM_EMAIL"]
TO_EMAIL = app.config["TO_EMAIL"]
SENDING_PHONE_NUMBER = app.config["SENDING_PHONE_NUMBER"]
API_KEY = app.config["API_KEY"]
API_SECRET = app.config["API_SECRET"]
ADMINISTRATORS = app.config["ADMINISTRATORS"]
BASE_URL = "https://rest.nexmo.com/sms/json?api_key={0}\
&api_secret={1}&type={2}&from={3}&to={4}&text={5}"

mail_on_500(app, ADMINISTRATORS)

def create_database():
	conn = sqlite3.connect("records.db")
	c = conn.cursor()
	c.execute("CREATE TABLE records (added real, mobile_number real, course_id text, confirmed integer, keycode integer)")
	conn.commit()
	conn.close()

@app.route("/")
def hello():
	# Simply display the homepage.
	return render_template('index.html')

@app.route("/receiveMessage", methods=['GET', 'POST'])
def handle_message():
	# Get the text message information.
	message = request.form["text"]
	phone = request.form["msisdn"]

	# Prepare the database.
	conn = sqlite3.connect("records.db")
	c = conn.cursor()

	if message[0:3] == "YES":
		# Grab the keycode.
		match = re.search("^YES (.*)$", message)
		keycode = match.group(1)

		# Set them to "confirmed"
		c.execute("UPDATE records SET confirmed = 1, added = ? WHERE mobile_number = ? AND keycode = ? AND confirmed = 0", \
			(str(int(time.time())), phone, keycode))

		# Ensure that the update was successful. If not, e-mail the admin and let the user know.
		if c.rowcount < 1:
			log_error("Confirmation unsuccessful with {0} and {1}".format(phone, keycode))
			msg_response = "Sorry, but 5C Enrollify had trouble processing your request."
		else:
			# Grab the course_id to use it in the response.
			c.execute("SELECT course_id FROM records WHERE mobile_number = ? AND keycode = ?", (phone, keycode))
			result = c.fetchone()
			course_id = result[0]

			msg_response = "Great! You'll now receive updates about {0}.".format(course_id)

	elif message[0:4] == "STOP":
		# Grab the keycode.
		match = re.search("^STOP (.*)$", message)
		keycode = match.group(1)

		# Delete them!
		c.execute("DELETE FROM records WHERE confirmed = 1 AND mobile_number = ? AND keycode = ?", \
			(phone, keycode))

		# Ensure that the update was successful. If not, e-mail the admin and let the user know.
		if c.rowcount < 1:
			log_error("Unsubscription unsuccessful with {0} and {1}".format(phone, keycode))
			msg_response = "Sorry, but 5C Enrollify had trouble processing your request."
		else:
			msg_response = "You'll no longer receive notifications about that class."
	else:
		# Tell them that I didn't understand their request!
		msg_response = "Sorry, but 5C Enrollify doesn't understand your input."

	# Send the response.
	send_message(phone, msg_response)

	# Close the database connection.
	conn.commit()
	conn.close()

	return "success", 200

@app.route("/addRecord", methods=['POST'])
def add_record_to_database():
	# Create the response object.
	response = make_response()

	# Grab the input from the asynchronous request.
	match = re.search("^([A-Z]+[0-9]+\s[A-Z]{2}-[0-9]{2}):.*$", str(request.form["course_id"]))
	course_id = match.group(1)
	phone = str("1" + request.form["phone"])

	# Create a keycode that'll be used to add/ remove the course listing.
	keycode = randint(10000, 99999)

	# Insert it into the database.
	conn = sqlite3.connect("records.db")
	c = conn.cursor()

	# Lazy check to see if the insertion succeeds.
	try:
		c.execute("INSERT INTO records VALUES (?, ?, ?, ?, ?)", (str(int(time.time())), phone, course_id, 0, keycode))
		conn.commit()
		conn.close()
	except Exception as exception:
		log_error("Addition unsuccessful: %s" % exception)
		response.status_code = 500
		return response

	# Send the user a confirmation message.
	message = "5C Enrollify received a request for this number to\
	receive updates about {0}. Reply with \"YES {1}\" to confirm this.".format(course_id, keycode)
	send_message(phone, message)

	# If all is good, return.
	response.status_code = 201
	return response

@app.route("/getCourses")
def get_current_courses():
	# Open the course information file.
	f = open('depts_courses.json', 'r')
	depts_info = json.loads(f.read())

	# Prepare the the output. FIXME: Store this in memory.
	course_strings = []
	for dept in depts_info:
		for course in dept["courses"]:
			title = course["course"] + " " + course["campus"] + "-" + course["section"] + ": " + course["title"]
			if title not in course_strings:
				course_strings.append(title)

	f.close()

	return json.dumps(course_strings)

# Sends the message to a receiver using the Nexmo API.
def send_message(receiver, text):
	type = "text"

	request = BASE_URL.format(API_KEY, API_SECRET, type, SENDING_PHONE_NUMBER, receiver, text)
	response = requests.get(request)
	data = json.loads(response.text)

	# If sending fails, send a message to the administrator.
	if data["messages"][0]["status"] != "0":
		body = "Received an error while trying to send a message: {0}".format(response.text)
		log_error(body)
		return False
	else:
		return True

# Sends a message to the e-mail defined above.
def log_error(body):
	smtp = smtplib.SMTP('localhost')
	msg = MIMEMultipart()
	msg["Subject"] = "5C Enrollify Error"
	msg["From"] = FROM_EMAIL
	msg["To"] = TO_EMAIL[0]
	msg.attach(MIMEText(body, "plain"))

	smtp.helo()
	smtp.sendmail(FROM_EMAIL, TO_EMAIL, msg.as_string())
	smtp.close()

	return True

if __name__ == "__main__":
    app.run(debug=True)
