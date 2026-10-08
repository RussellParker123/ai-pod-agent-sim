"""
Dr. Cypher - Original AI Scientist Character (module keeps the older
"dr_cipher" spelling for compatibility).
A mad scientist manager for the simulation arena.
"""

def get_dr_cipher_svg():
    """Returns SVG code for Dr. Cipher character"""
    svg = """
    <svg viewBox="0 0 200 300" xmlns="http://www.w3.org/2000/svg" style="max-width: 280px; max-height: 420px;">
        <defs>
            <style>
                @keyframes floatBounce {
                    0%, 100% { transform: translateY(0px); }
                    50% { transform: translateY(-15px); }
                }
                @keyframes glow {
                    0%, 100% { filter: drop-shadow(0 0 8px #00ff41); }
                    50% { filter: drop-shadow(0 0 20px #00ccff); }
                }
                .dr-cipher { animation: floatBounce 2.5s infinite; }
                .dr-cipher-glow { animation: glow 3s infinite; }
            </style>
        </defs>
        
        <!-- Glow container -->
        <g class="dr-cipher-glow">
            <!-- Body group with animation -->
            <g class="dr-cipher">
                <!-- Lab Coat -->
                <path d="M 60 80 L 50 180 Q 50 200 70 200 L 130 200 Q 150 200 150 180 L 140 80 Z" 
                      fill="#e8e8e8" stroke="#333" stroke-width="2"/>
                
                <!-- Coat Accents (cyan/teal) -->
                <rect x="55" y="85" width="90" height="8" fill="#20d9d9" opacity="0.7"/>
                <line x1="100" y1="85" x2="100" y2="200" stroke="#20d9d9" stroke-width="2" opacity="0.5"/>
                
                <!-- Head -->
                <circle cx="100" cy="50" r="35" fill="#d4a574" stroke="#333" stroke-width="2"/>
                
                <!-- Hair - Spiky Style -->
                <polygon points="70,25 65,5 75,20" fill="#1a9db8" stroke="#0d5a70" stroke-width="1.5"/>
                <polygon points="85,15 80,0 90,12" fill="#1a9db8" stroke="#0d5a70" stroke-width="1.5"/>
                <polygon points="100,10 95,0 105,10" fill="#2ab8d4" stroke="#0d5a70" stroke-width="1.5"/>
                <polygon points="115,15 110,0 120,12" fill="#1a9db8" stroke="#0d5a70" stroke-width="1.5"/>
                <polygon points="130,25 135,5 125,20" fill="#1a9db8" stroke="#0d5a70" stroke-width="1.5"/>
                
                <!-- Hair back -->
                <ellipse cx="100" cy="40" rx="32" ry="28" fill="#1a9db8" stroke="#0d5a70" stroke-width="1.5" opacity="0.8"/>
                
                <!-- Eyes -->
                <circle cx="85" cy="45" r="5" fill="white" stroke="#333" stroke-width="1"/>
                <circle cx="85" cy="45" r="3" fill="#000"/>
                
                <circle cx="115" cy="45" r="5" fill="white" stroke="#333" stroke-width="1"/>
                <circle cx="115" cy="45" r="3" fill="#000"/>
                
                <!-- Eye glasses/goggles overlay -->
                <circle cx="85" cy="45" r="6.5" fill="none" stroke="#666" stroke-width="1.5" opacity="0.6"/>
                <circle cx="115" cy="45" r="6.5" fill="none" stroke="#666" stroke-width="1.5" opacity="0.6"/>
                <line x1="91.5" y1="45" x2="108.5" y2="45" stroke="#666" stroke-width="1.5" opacity="0.6"/>
                
                <!-- Nose -->
                <polygon points="100,50 97,58 103,58" fill="#b8956a"/>
                
                <!-- Mouth - Mad Grin -->
                <path d="M 85 65 Q 100 75 115 65" stroke="#333" stroke-width="2" fill="none" stroke-linecap="round"/>
                <path d="M 88 68 Q 100 72 112 68" stroke="#ff6b00" stroke-width="1" fill="none" stroke-linecap="round"/>
                
                <!-- Tongue (slightly out) -->
                <ellipse cx="100" cy="72" rx="4" ry="3" fill="#ff9999"/>
                
                <!-- Left Arm -->
                <line x1="65" y1="95" x2="45" y2="130" stroke="#9a9a9a" stroke-width="8" stroke-linecap="round"/>
                
                <!-- Left Hand -->
                <circle cx="40" cy="135" r="7" fill="#d4a574" stroke="#333" stroke-width="1.5"/>
                <line x1="35" y1="132" x2="32" y2="128" stroke="#d4a574" stroke-width="2" stroke-linecap="round"/>
                
                <!-- Right Arm -->
                <line x1="135" y1="95" x2="155" y2="110" stroke="#9a9a9a" stroke-width="8" stroke-linecap="round"/>
                
                <!-- Portal Device (in right hand) -->
                <g transform="translate(165, 105)">
                    <rect x="-8" y="-12" width="16" height="20" fill="#4a4a4a" stroke="#333" stroke-width="1" rx="2"/>
                    <circle cx="0" cy="-6" r="5" fill="#00ff41" opacity="0.8"/>
                    <circle cx="0" cy="-6" r="4" fill="#00ff41" opacity="0.4"/>
                    <rect x="-6" y="4" width="12" height="3" fill="#ffaa00"/>
                </g>
                
                <!-- Legs -->
                <line x1="80" y1="200" x2="75" y2="240" stroke="#4a4a4a" stroke-width="6" stroke-linecap="round"/>
                <line x1="120" y1="200" x2="125" y2="240" stroke="#4a4a4a" stroke-width="6" stroke-linecap="round"/>
                
                <!-- Shoes -->
                <ellipse cx="75" cy="245" rx="6" ry="5" fill="#1a1a1a" stroke="#333" stroke-width="1"/>
                <ellipse cx="125" cy="245" rx="6" ry="5" fill="#1a1a1a" stroke="#333" stroke-width="1"/>
            </g>
        </g>
        
        <!-- Neon border -->
        <rect x="5" y="5" width="190" height="290" fill="none" stroke="#ff6b9d" stroke-width="2" rx="10" opacity="0.6"/>
    </svg>
    """
    return svg


def get_cipher_quotes():
    """Returns Dr. Cypher's original personality lines by performance tier.
    (Internal function/module names keep the older "cipher" spelling.)"""
    return {
        "excellent": [
            "Prototype accepted. Log it, frame it, then make the next one sharper.",
            "Every brief hit its print area. I may have to update my expectations upward.",
            "Clean compliance, healthy margins. The lab coat stays on for the photo.",
            "Remarkable. The agents followed the notes instead of arguing with them.",
        ],
        "good": [
            "Solid work. The data agrees with me, which is how I like it.",
            "Functional and sellable. Tighten the palettes and we talk about excellence.",
            "Acceptable. A few prompts still read like guesses rather than briefs.",
            "Progress noted on the clipboard. Do not make me erase it.",
        ],
        "mediocre": [
            "Some of this holds up. The rest goes back to the bench with notes.",
            "Half the batch forgot the product it was designed for. Re-read the brief.",
            "Adequate is not a product category. Show me focal motifs.",
            "The goggles are fogging up from disappointment. Rework the flagged ones.",
        ],
        "poor": [
            "Nothing ships until the blockers are gone. Back to the drawing tablets.",
            "These concepts would not survive a thumbnail. Start from the brief.",
            "Compliance flags everywhere. Nobody touches the publish button today.",
            "I have reviewed coffee stains with stronger composition. Again, with notes.",
        ],
    }
