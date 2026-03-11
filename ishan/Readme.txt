File
record_hand.py : Records the radar fingerprint of the hand and the empty scene
detect_hand.py : Live detector; show red dot when hand is detected
hand_signature.npy : Auto generated after recording hand's radar fingerprint
empty_signature.npy : Auto generated after recording empty scene fingerprint

Install
pip install ifxradarsdk numpy matplotlib scipy
pip install path\to\ifxradarsdk-3.6.4-py3-none-win_amd64.whl (if not already)

How to Run
Step1: Record the signatures
This only needs to be done once. The .npy files are saved and resused every time after. 
Run the recording script: python record_hand.py

1of2 First, place hand 30-50 cm in front of radar 
2of2 Remove hand, nothing in front of radar. Keep still

Step2: Run the detector
python detect_hand.py