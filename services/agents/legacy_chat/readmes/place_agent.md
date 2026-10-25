![tag:innovationlab](https://img.shields.io/badge/innovationlab-3D8BD3)
![tag:hackathon](https://img.shields.io/badge/hackathon-5F43F1)

# Streetwise Shop Agent (SIMULATED DEMO)

**This agent is SIMULATED for a hackathon demo.** It represents one shop (a real place id from the Streetwise engine) and answers `HoursQuery(place_id, day, minute)` with the hours it *declares* in `demo_places.json`, not hours confirmed by the real business. Scout asks it whether the shop will be open when a walker passes and, if it confirms, the engine re-scores the route. In production a business would run its own shop agent.
