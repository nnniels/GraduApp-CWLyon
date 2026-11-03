# Introduction

We are looking to create a simple web app that will be served to a few people, for a limited period of time. The app will be hosted on a Linux computer, out of corporate network, or on a personnal server out of corporate network.

This is a friendly game, cheating is not an issue. No QR or GPS needed for validation. Each team will have someone with them, that will give them a code to input in the validation popup to validate locations. However, not exposing the host or the user's smartphones is important.

# Web App concept

There will be several (2 to 5) teams of roughly 5 people. Each team will have access to the web app on one phone.
The app will guide the groups through a pre-defined itinerary. There will be several itineraries. An itinerary will be allocated to a team prior to the game starting. There will also be a pre-defined list of challenges each team will try to complete.

The itinerary is made of many steps.
A step is decomposed like this :
1. Go to a Location. the Location is either directly given as a Google maps link, or as text, or shown on a minimap.
2. The user confirms that it has reached the Location. Some new challenges might be unlocked, they are then added to the challenges list.
Then, either 3a or 3b happens.
3.
  a. A list of location-related challenges is given to the user to complete. They are limited in time. A clock is shown. When the user has completed k challenges out of the n proposed, the Location is validated and a new Location is provided to the user. Else, the challenge are considered failed, a pop-up appears saying so. The user cannot complete the challenges, and a new Location is provided to the user.
  b. A riddle is given to the user. The user submit an answer. The answer is always considered true (it will be checked afterward). After the user has entered the answer, the Location is validated and a new Location is provided to the user.

At all time, the team can switch to making challenges in the Location they are at. Thoses general-purpose challenges are different from location-specific challenges.

# Technical Choices
For now, we are looking to develop this app using Flask and a Cloudflare Tunnel. The UI will use Jinja templates + HTMX. The server owns the state. Progress is stored on the server.
The itineraries and team progress will be stored using SQLite.

# Screens
Only recent smartphones will open this webapp. The layout will hence be mde for vertical scrolling, high lisibility

A. On first start, a screen for the user to select its team.
B. A Itinerary screen that display the information to get to the location, or the Riddle, or location-related challenges
C. A challenge list that display the completed challenges, and the one still to complete. It updates when the user unlock new challenges.

Switching between B and C can be done using a toggle.

Layout :
A. Simple list of the pre-defined teams. Name of the team can be inputed/edited. Confirm before validation. Confirmation requires a code, which ensure each team has selected its right pre-defined team on the app.
B. Team name atop. Toggle between B and C just below. Three configurations are possible for this screen : 
  1. *going to a location*. Display the location juste below the toggle (as text or minimap). 'I am here' button just below. on click, a pop-up with the new challenges that are unlocked, or a simple success pop-up.
  2. *riddle*. Display the riddle as text and/or image, input field for the answer, and a 'submit answer button'.
  3. *location-related challenges*. Display a list of challenges, with a timer below. The timer roughly takes the space that was occupied by the button on the previous screens. The user can tick a challenge. A pop-up with an input appear when ticking a challenge. the user can undo a challenge, after pressing 'challenge uncompleted' in a popup to cancel.
  4. *end reached*. A simple end screen, with an image and a text.
C. Team name atop. Toggle between B and C just below. Below the toggle, a list of general-purpose challenges. The user can tick the challenges. A pop-up with an input appear when ticking a challenge.


# Data model
- Team(id, name, itinerary_id, join_code)
- TeamState(team_id, step_index, phase, phase_deadline)
- Event(id, team_id, type, payload_json, ts), which is the audit log and the source for review
- Content (YAML): Itinerary → Steps → {location, riddle | challenges, unlocks}, plus GeneralChallenges

Plus likely a Challenge(text)


