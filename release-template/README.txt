Made using Python 3.11.11 and Spyder 6.0.4

Change chem and stats in the first 4 tabs, and then generate the gecko code in the 5th.

Added in version 3.0 : the traj height tab ! You can now change how the trajectories are defined
Added in version 3.1 : various bug fixing, real stamina has been found, as well as star swing/pitch editing
Added in version 3.2 : added the names of various stats, copy gecko code button, and changes to gecko from selection,
		        dev mode and reverse functions to wacky changes
Added in version 3.3 : added the chem graph random function, which is a different method to generate a full random chem
			as well as bug fixing to the stat randomizer and gecko code generator. No longer using numpy
Added in version 3.4 : added a gecko code loader, that reads chem and stats changes from a gecko code directly
Added in version 3.5 : fix to the gecko loader, executable now available !


Either run the sluggers-stat-editor.exe, or you can find the source code in the "Source Code" folder

Chemistry tab :
Choose direction and chem type, then pick two characters/groups
For the randomizer, adjust ratios, select options, then press "Randomize each chem"
Alternatively, choose the average amount of bad and good chem, as well as the max deviation from those average
then press "Create Random Graph"

Stat Editor tab:
Chose a character/group, check the stats to change, select a value, then choose your action

Stat Randomizer tab:
Check stats to change, choose min and max values, as well as range if you select "modify around stats"
Add the characters/groups you want to randomize one by one, select options, then press the big red button
Note : Updated displayed stats depend on the min and max for the relevant stat, may lead to weirdness

Traj Height tab:
Choose a trajectory group to edit, rename it if you want
If you wish to add a new group, don't forget to check "use traj group"

Gecko Code tab:
Press "Generate entire code". If the code is too big (alert comes up), only generate the relevant characters for the game/team
You can also choose to only generate the code for some characters, while making sure the others are untouched (vanilla stats)
You can save and load the changes made, stored in a .txt file in the "Save Files" folder.
You can also load changes made from a gecko code directly, simply put the gecko code in a .txt file in the "Gecko Codes" folder,
enter the file name and press "Load gecko code". Note that it can only read gecko commands starting with 00,02,04,06 or 08.

Wacky stuff tab:
Dev mode allows you to input any number in the double-byte stats.
Reverse buttons reverses the stats according to the current stats (so it will also reverse any change you made).
For reverse stats, it will reverse around the midpoint between the max and min of that stat in vanilla, big outliers excluded)

Credits tab:
Credits where credit is due :)