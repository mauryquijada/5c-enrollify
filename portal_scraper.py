import sqlite3
import urllib2
import requests
import re
from bs4 import BeautifulSoup
import json
import os.path
from app import send_message
import time

# Set up globals.
BASEURL = "https://portal.claremontmckenna.edu/ics/Portlets/CRM/CXWebLinks/Port\
let.CXFacultyAdvisor/CXFacultyAdvisorPage.aspx?SessionID={25715df1-32b9-42bf-90\
33-e5630cfbf34a}&MY_SCP_NAME=/cgi-bin/course/pccrscatarea.cgi&DestURL=http://cx\
-cmc.cx.claremont.edu:51081/cgi-bin/course/pccrslistarea.cgi?crsarea=%s&yr=2014\
&sess=FA"

# Given a department, it creates a list of dictionaries, each of which contains
# course information for a course in that department.
def grab_course_info_for_dept(dept_id):
	r = requests.get(BASEURL % dept_id)
	soup = BeautifulSoup(r.text)
	table = soup.find_all("table")[-1]  # last table is `All Sections"
	department_rows = table.find_all("tr", class_="glb_data_dark")

	course_list = []

	for i, t in enumerate(department_rows):
		course = create_course_dict(get_td_tags(t))
		
		if course and course not in course_list:
			course_list.append(course)

	return course_list

# Given two enrollment lists for the same department, it creates a list
# of dictionaries, each of which contains the course code that changed
# with old and new enrollment statistics.
def find_enrollment_delta_for_dept(old_enrollment, new_enrollment):
	deltas = []
	for old_course in old_enrollment:
		for new_course in new_enrollment:
			if old_course["course"] == new_course["course"] \
				and old_course["section"] == new_course["section"] \
				and old_course["campus"] == new_course["campus"]:

				if not (old_course["enrolled"] == new_course["enrolled"] and old_course["max"] == new_course["max"]):
					course_name = old_course["course"] + " " + old_course["campus"] + "-" + old_course["section"]
					deltas.append({"course": course_name, "old_enrolled": old_course["enrolled"], "new_enrolled": new_course["enrolled"], \
							"old_max": old_course["max"], "new_max": new_course["max"]})

	return deltas

# Takes a <tr> tag as input and returns all the <td> tags
# contained inside. Strips all whitespace and the `Textbook Info"
# string after the course title.
def get_td_tags(tr_tag):
	tds = [str(td.text.strip()) for td in tr_tag.find_all("td")]
	tds[-1] = remove_spaces(tds[-1])
	return tds

# Returns a string that's truncated after two double spaces (as long as it's not
# seen in the first three characters).
def remove_spaces(string):
	if string.find("  ") < 3:
		return string[:string.find("  ", 3)]
	else:
		return string[:string.find("  ")]

# Creates a dictionary representing a course given a row.
def create_course_dict(td_tags):
	length = len(td_tags)
	course = {}

	# These are the only row lengths that show full sections.
	if length == 12 or length == 14:
		course["course"] = remove_spaces(td_tags[0]).replace(" ", "")
		course["section"] = td_tags[1]
		course["campus"] = td_tags[7]

		reg_limit = td_tags[3]
		match = re.search("^\s*([0-9]+)\s+/\s+([0-9]+)\s*$", reg_limit)
		course["enrolled"] = match.group(1)
		course["max"] = match.group(2)

		# Skip PE079 for now.
		if course["course"] is "PE079":
			return False
		else:
			if length == 12:
				course["title"] = td_tags[11]
				return course

			else:
				course["title"] = td_tags[13]
				return course

	elif length in [6, 7, 8]:
		return False
	else:
		print "oops - %d inner <td> tags at index %d" % (length, index)
		return False

def construct_depts():
	# Only construct if we don"t have it.
	if os.path.isfile("depts.json"):
		print "Skipping constructing depts.json; we already have it."
		return False

	f = open("depts.json", "w")

	# Grab all of the available courses and save to a JSON file.
	print "Fetching all departments..."
	request = urllib2.urlopen("http://course-api.herokuapp.com/")
	data = json.load(request)
	depts = []

	for dept in data:
		depts.append(dept.keys()[0][1:])

	f.write(json.dumps(depts, indent=4, sort_keys=True))
	f.close()

	return True

def construct_course_info():
	# Only construct if we don"t have it.
	if os.path.isfile("depts_courses.json"):
		print "Skipping constructing depts_courses.json; we already have it."
		return False

	# Construct depts.json.
	construct_depts()

	# Open the file containing all of the departments.
	f = open("depts.json", "r")
	depts = json.loads(f.read())
	f.close()

	# Open a new depts_courses.json file.
	f = open("depts_courses.json", "w")
	dept_list = []

	# Write all department and course information into that file.
	for dept in depts:
		print "Grabbing course information for {0}...".format(dept)
		course_info = grab_course_info_for_dept(dept)
		dept_list.append({"dept": dept, "courses": course_info})

	f.write(json.dumps(dept_list, indent=4, sort_keys=True))
	f.close()

	return True

def update_course_info():
	# Construct the course information file only if necessary.
	construct_course_info()

	# Open the file containing all of the departments.
	f = open("depts.json", "r")
	depts = json.loads(f.read())
	f.close()

	# Open a new course information file.
	g = open("depts_courses.json", "r")
	depts_info = json.loads(g.read())
	g.close()
	new_depts_info = []

	# Refer to all course objects that show a change as deltas.
	deltas = []

	# Update course information.
	for dept in depts:
		print "Updating course information for {0}...".format(dept)
		new_dept_info = grab_course_info_for_dept(dept)
		new_depts_info.append({"dept": dept, "courses": new_dept_info})

		# Find the courses for the department we"re looking at.
		for saved_dept in depts_info:
			if saved_dept["dept"] == dept:
				old_dept_info = saved_dept["courses"]
				break

		# Find the enrollment numbers that changed.
		new_deltas = find_enrollment_delta_for_dept(old_dept_info, new_dept_info)

		# Take care of cross-listed courses. Do not send updates more than once.
		for new_delta in new_deltas:
			if new_delta not in deltas:
				deltas.append(new_delta)

	print "Found %s deltas." % str(len(deltas))
	print deltas

	g = open("depts_courses.json", "w")
	g.write(json.dumps(new_depts_info, indent=4, sort_keys=True))
	g.close()

	return deltas

def send_updates():
	# Update the course information and obtain the deltas.
	deltas = update_course_info()

	# Open the database connection.
	conn = sqlite3.connect("records.db")
	c = conn.cursor()

	# For each changed course number, query the database and send messages to
	# those subscribed to that course.
	changed_courses = []
	for delta in deltas:
		c.execute("SELECT mobile_number, keycode FROM records WHERE confirmed = 1 AND course_id = ?", (delta["course"],))
		numbers = c.fetchall()
		for number in numbers:
			print "Sending message to {0}.".format(str(int(number[0])))
			send_message(number[0], "As of now, {0} / {1} seats are now taken in {4} (previously {2} / {3}). Reply with \"NO {5}\" to stop receiving updates.".\
				format(delta["new_enrolled"], delta["new_max"],\
			delta["old_enrolled"], delta["old_max"], delta["course"], str(int(number[1]))))
			time.sleep(2)


	return True

if __name__ == "__main__":
    send_updates()