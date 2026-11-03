You are reading one digital display on a valve in a process plant, cropped from a camera frame and enlarged.

The display shows the valve position as a whole number of percent open, from 0 to 100, in green digits on a black screen.
- The number is right-aligned: a short number such as 0 or 5 sits at the right edge with empty black screen to its left. That empty space is normal and does not mean the number is cut off.
- A single digit is a complete reading. "0" means the valve reads fully closed; read it as 0.
- Read every digit that is shown: 1, 10 and 100 are different readings. Never drop a digit, and never report 0 unless the only digit shown is 0.
- Report the number exactly as shown. Do not estimate it from the valve, a dial or anything else in the picture.
- If the digits are blurred, covered or partly outside the picture, or you are not certain of every digit, the display is not readable: set "readable" to false and "value" to null.
- Never guess a value.

Reply with JSON only: {"value": <number or null>, "readable": <true or false>}
