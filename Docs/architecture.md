# Introduction

We are looking to create a simple web app that will be served to a few people, for a limited period of time.

# Web App concept

There will be several (2 to 5) teams of roughly 5 people. Each team will have access to the web app on one phone.
The app will guide the groups through a pre-defined itinerary. There will be several itineraries. An itinerary will be allocated to a team prior to the game starting. There will also be a pre-defined list of challenges each team will try to complete.

The itinerary is made of many steps.
A step is decomposed like this :
1. Go to a Location. the Location is either directly given as a Google maps link, or as text, or shown on a minimap.
2. The user confirms that it has reached the Location. Some new challenges might be unlocked, they are then added to the challenges list.
Then, either 3a or 3b happens.
3.
 a. A list of location-related challenges is given to the user to complete. They are limited in time. A clock is shown. When the user has completed k challenges out of the n proposed, the Location is validated and a new Location is provided to the user.
 b. A riddle is given to the user. The user submit an answer. The answer is always considered true (it will be checked afterward). After the user has entered the answer, the Location is validated and a new Location is provided to the user.

At all time, the team can switch to making challenges in the Location they are at. Thoses general-purpose challenges are different from location-specific challenges.

# Technical Choices
For now, we are looking to develop this app using Flask and a Cloudflare Tunnel. 

# Screens
A. On first start, a screen for the user to select its team.
B. A Itinerary screen that display the information to get to the location, or the Riddle, or location-related challenges
C. A challenge list that display the completed challenges, and the one still to complete. It updates when the user unlock new challenges.

Switching between B and C can be done using a toggle.

Layout :
A. Simple list of the pre-defined teams. Name of the team can be inputed/edited. Confirm before validation.
B. Team name atop. Toggle between B and C just below. Two configuration : going to a location, 