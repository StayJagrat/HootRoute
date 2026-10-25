import { Navigate, Route, Routes } from 'react-router-dom';
import Home from './screens/Home';
import Setup from './screens/Setup';
import Plan from './screens/Plan';
import Walk from './screens/Walk';
import Guardian from './screens/Guardian';
import Shop from './screens/Shop';
import Room from './screens/Room';
import Intro from './screens/Intro';

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<Home />} />
      <Route path="/welcome" element={<Intro />} />
      <Route path="/plan" element={<Plan />} />
      <Route path="/setup" element={<Setup />} />
      <Route path="/walk" element={<Walk />} />
      <Route path="/guardian/:walk" element={<Guardian />} />
      <Route path="/guardian" element={<Navigate to="/guardian/demo" replace />} />
      <Route path="/shop/:place" element={<Shop />} />
      <Route path="/shop" element={<Shop />} />
      <Route path="/room" element={<Room />} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
