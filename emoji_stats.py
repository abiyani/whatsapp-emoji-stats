#!/usr/bin/env python
from __future__ import print_function
import re
import sqlite3
import sys
import pickle
import collections as coll
import os
import argparse


def removeNonAscii(s):
    return "".join(filter(lambda x: ord(x) < 128, s))

##################
# Parse arguments
parser = argparse.ArgumentParser(description='Create a histogram of emoji usage for any whatsapp contact or group')
parser.add_argument('-m', '--msg-db', metavar="path", default="msgstore.db", help='Path to Message DB (msgstore.db)')
parser.add_argument('-c', '--contacts-db', metavar="path", default="wa.db", help='Path to Contacts DB (wa.db)')
group = parser.add_mutually_exclusive_group(required=True)
group.add_argument('-r', '--group-or-contact-regexp', metavar="regexp",
                   help='Regular expression matching a  the target contact or group name (case insensitive)')
group.add_argument('-i', '--group-or-contact-id', metavar="id_str",
                   help='Exact group id matching the target contact or group (case sensitive).' +
                   'This is useful when you have two different whatsapp contacts with exact same name ' +
                   '(so cannot distinguish using the regexp option (--group-or-contact-regexp)')

args = parser.parse_args()
if not os.path.isfile(args.contacts_db) or not os.path.isfile(args.msg_db):
    sys.stderr.write("ERROR: At least one of the DB path is incorrect.\n")
    parser.print_help()
    sys.exit(1)

if not args.group_or_contact_regexp and not args.group_or_contact_id:
    sys.stderr.write("ERROR: Exactly one of the '--group-or-contact-regexp' or '--group-or-contact-id' must be provided.\n")
    parser.print_help()
    sys.exit(1)
###################

#############################################################
# Read all contacts and create a id=>name dict (all_contacts)
conn = sqlite3.connect(args.contacts_db)
c = conn.cursor()
q = c.execute('SELECT jid, display_name FROM wa_contacts WHERE display_name IS NOT NULL')
all_contacts_tuple = q.fetchall()
all_contacts = {i[0]: i[1] for i in all_contacts_tuple}  # Create dict of ID => name
##############################################################

#####################################################
# Now find the id of the group/contact user provided
if args.group_or_contact_id:
    grp_or_contact_id = args.group_or_contact_id
    if grp_or_contact_id not in all_contacts:
        sys.stderr.write("ERROR: Invalid id '{}' - does not exist in the contacts db\n".format(grp_or_contact_id))
        sys.exit(1)
else:
    tre = args.group_or_contact_regexp
    matching_names = [i for i in all_contacts if re.search(tre, all_contacts[i], re.IGNORECASE)]

    if len(matching_names) == 0:
        sys.stderr.write("No match found in the contacts db for the regexp '{}'.".format(tre))
        sys.exit(1)

    if len(matching_names) > 1:
        sys.stderr.write("\nERROR: Too many matches found for the regular expression '{}', please narrow it down (or specify id using '--group-or-contact-id'). " +
                         "Below are all the matches for this regexp:\n\n".format(tre))
        sys.stderr.write("\n".join([removeNonAscii(all_contacts[i]) + " (id = '{}')".format(i) for i in sorted(matching_names, key=lambda x:all_contacts[x])]) + "\n")
        sys.exit(1)

    grp_or_contact_id = matching_names[0]
    sys.stderr.write("Found exactly one match for the regular expression: '{}' (id = '{}'). Will generate statistics for it\n".format(tre,
        removeNonAscii(all_contacts[grp_or_contact_id])))
#####################################################

all_contacts["me"] = "Me"  # Special case

#################################################
# Now read all the relevant data from message db
conn = sqlite3.connect(args.msg_db)
c = conn.cursor()

querystr = 'SELECT data, remote_resource, key_remote_jid, key_from_me, status ' + \
           'FROM messages ' + \
           'WHERE key_remote_jid=? AND media_mime_type IS NULL AND media_name IS NULL'  # ? will be filled in using sqlite's DB-API's param substitution (see .execute() below)

q = c.execute(querystr, (grp_or_contact_id,))
rows = q.fetchall()  # indices in each row: data: 0, remote_resource: 1, key_remote_jid: 2, key_from_me: 3, status: 4 (see SQL query above)
if len(rows) == 0:
    sys.stderr.write("ERROR: No whatsapp data found for user/contact '{}'.\nSQL Query:\n'{}'\n (? = '{}')\n".format(
        grp_or_contact_id, querystr, grp_or_contact_id))
    sys.exit(1)
#################################################

#####################################################
# Store the data in more usable form: id => all_msgs
user_to_msg = coll.defaultdict(unicode)  # ID => all_msgs_concatenated (all messages for same id are concatenated with " " in between (as we just care about count of emojis))
total_msg_count = 0
for r in rows:
    if isinstance(r, tuple) and r[0] is not None:
        assert r[2] == grp_or_contact_id, "Problem row = {}".format(r)  # Sanity check (since we queried for a fixed 'key_remote_jid' value, this field should be same for all rows)
        total_msg_count += 1
        if r[3] == 1:
            user = "me"
            if r[4] not in (5, 6):  # 6 is for group name change, 5 is broadcast
                assert r[1] is None, "Problem row = {}".format(r)  # Sanity check, if message was sent by me, then remote_resource field should be empty
        elif r[1] == u'':
            assert "@s." in grp_or_contact_id, "Problem row = {}".format(r)  # Must be a one-to-one chat in this case
            user = r[2]
        elif "@g." not in grp_or_contact_id:
            assert r[1].endswith("@broadcast"), "Problem row = {}".format(r)  # Still not a group chat => It should be a broadcast message
            user = r[2]
        else:
            assert "@g." in grp_or_contact_id, "Problem row = {}".format(r)  # Must be a group
            user = r[1]
        user_to_msg[user] += r[0]
#####################################################

########################################
# Write the common header for html file
print ("""
<!DOCTYPE html>
<html>
    <head>
        <title>Emoji Statistics for {}</title>
        <meta http-equiv="Content-type" content="text/html; charset=utf-8">
        <!-- DataTables CSS -->
        <link rel="stylesheet" type="text/css" href="http://cdn.datatables.net/1.10.0/css/jquery.dataTables.css">

        <!-- jQuery -->
        <script type="text/javascript" charset="utf8" src="http://code.jquery.com/jquery-1.10.2.min.js"></script>

        <!-- DataTables -->

        <script type="text/javascript" charset="utf8" src="http://cdn.datatables.net/1.10.0/js/jquery.dataTables.js"></script>
        <script>
            $(document).ready( function () {{
                $('#emoji_table').dataTable({{
                    "aLengthMenu": [[25, 50, 100, 200, -1], [25, 50, 100, 200, "All"]],
                    "iDisplayLength" : -1,
                    "bFilter": false
                }});
            }});
        </script>
    </head>
    <body>
        <h1>Stats for '{}'</h1>
        <pre>
""".format(*(removeNonAscii(all_contacts.setdefault(grp_or_contact_id, grp_or_contact_id.split("@")[0])),) * 2))

########################################

#################################################################################################
# emoji pickle file contain a dictionary of: unicode_of_emoji => base64_encoded_png_of_the_emoji
emoji_pickle_file = os.path.join(os.path.dirname(os.path.realpath(__file__)), "all_emojis_base64.p")
with open(emoji_pickle_file, "rb") as f:
    emoji_to_base64 = pickle.load(f)
#################################################################################################

rexp = re.compile("(" + "|".join(emoji_to_base64.keys()) + ")")  # A catch-all-emoji regular expression
final_count = {e: coll.defaultdict(int) for e in emoji_to_base64}  # Initialize a 2d dict of this form: [<EmojiUnicodeValue>][<ID>] => count (will store result in it)
for user in user_to_msg:
    for match in re.finditer(rexp, user_to_msg[user]):
        final_count[match.group()][user] += 1

#######################################
# Now start writing the complete table
#
# Start with printing column headers first
all_users = user_to_msg.keys()
print ("""
        <table border=2 id=emoji_table>
            <thead>
            <tr>
                <th>Emoticon</th><th>Total</th>
""")
for user in all_users:
    print ("\t\t\t\t<th>{}</th>".format(all_contacts.setdefault(user, user.split("@")[0])))
print ("""
    </tr>
    </thead>
    <tbody>
    """)

# Now print the final emoji count table (sorted by total occurrence of a emoji)
for tup in sorted(final_count.items(), key=lambda x: sum(x[1].values()), reverse=True):
    emoji = tup[0]  # shorthand
    if sum(final_count[emoji].values()) == 0:  # Do not write emojis which haven't been used at all
        break
    print ("\t\t\t<tr>\n\t\t\t\t<td><img src='data:image/png;base64, {}'/></td>".format(emoji_to_base64[emoji]))
    print ("\t\t\t\t<td>{}</td>".format(sum(final_count[emoji].values())))
    for users in all_users:
        print ("\t\t\t\t<td>{}</td>".format(final_count[emoji][users]))
    print ("\t\t\t</tr>")

# Print the common footer
print ("""
                </tbody>
            </table>
        </pre>
    </body>
</html>
""")
#######################################
sys.stderr.write("Done!\n")
