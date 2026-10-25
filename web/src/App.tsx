import { Navigate, Route, Routes } from 'react-router-dom';
import Guardian from './pages/Guardian';
import Plan from './pages/Plan';
import Walk from './pages/Walk';

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<Plan />} />
      <Route path="/walk" element={<Walk />} />
      <Route path="/guardian/:walk" element={<Guardian />} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
