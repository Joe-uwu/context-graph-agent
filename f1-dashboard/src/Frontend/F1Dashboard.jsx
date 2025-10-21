import React from 'react';
import './F1Dashboard.css';
import mainF1Image from './Main-F1-image.png';

const Card = ({ title, subtitle }) => (
  <div className="card">
    <div className="star">★</div>
    <h3>{title}</h3>
    <p>{subtitle}</p>
  </div>
);


const F1Dashboard = () => {
  return (
    <div className="dashboard">
      <div className="content">
        <div className="cards-container">
          <h2>Card</h2>
          <div className="cards-grid">
            <Card title="F1 Race Predictor" subtitle="sub-title" />
            <Card title="Title" subtitle="sub-title" />
          </div>
          <h2>Frame 14405</h2>
          <div className="cards-grid">
            <Card title="Title" subtitle="sub-title" />
            <Card title="Title" subtitle="sub-title" />
          </div>
        </div>
      </div>
      <div className="image-container">
        <img src={mainF1Image} alt="F1 Race" className="main-image" />
        <div className="gradient-overlay"></div>
      </div>
    </div>
  );
};

export default F1Dashboard;