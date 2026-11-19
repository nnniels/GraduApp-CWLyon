Your are an expert web developer with a sharp eye.

We are working on improving the app look and feel. The interface is ergonomic enough, this just styling.

# Design of the App

Make the color parametrized, so that there is one source of truth for the app theme.

## Overall design
Colors : dark blue and dark red accent, white bold fonts.

Background : dark grey.

Fonts : Squared, sporty. Boxy and bold for titles. Very readable on a phone screen.

Buttons : Rectangle shape, minimal corner rounding, 
- accentuated : dark blue to dark red gradient, bold white lettering, minimal thin light blue edges
- not accentuated : very dark grey background, bold white lettering, minimal thin light blue edges

**The screens will keep the same overall layout. Only the look and feel will be updated.**

The images are stored in content/images/ for now.

## Screen A (pick your team)
Dark background.
From top to bottom :
- App Title (included as a transparent image)
- A skyline of the city (included as a transparent image)
- A dark purple horizontal ligne as separator
- A Bold, choose your team title
- The team cards. The box of the team card have each a different color on the edges (blue, red, purple, light grey). If there is more than 4 cards, a color can be present twice or more. The confirm button has accentuated style defined above. The box is squared, with top right and bottom left corner rounded.

## Screen A to B (team registration confirmation screen)
From top to bottom :
- App Title (included as a transparent image)
- A skyline of the city (included as a transparent image)
- The confirmation box is squared, with top right and bottom left corner rounded, corners the color of the team (blue, red, purple, light grey). 
- The Start The Game button has accentuated style defined above.


## Screen B
- App Title (included as a transparent image) is still present, but smaller and on the left side.
- The fact that the two buttons acting as tabs switches is made clearer. They are highlighted with white font and dark red shadow when selected. They are light grey when not selected.

### Challenge list tab
- A progression bar (green on dark grey) is shown at the top of the list saying how many challenges are completed (eg 3 of 15 completed).
- Each challenge is in a light blue box. New badge is gold color, thick font.
- Done challenges have a green tick and a green box.

### Direction tab
- A progression bar (purple on dark grey) is shown just above the instruction saying how much of the destination have already been covered.
- The instruction is highlighted with white font and dark red shadow.
The open google maps button is not accentuated
The I am here button is accentuated

For the pop-ups, the 'validation'-role button is accentuated, the cancel-role button is not.

## End screen
Use the flag included as a transparent image.


# Task
Update the design of the app by updating the templates. Make elements (button, etc) shared & common when relevant. Do not run tests, I will do that.