// src/dashboard/onboarding/OnboardingWizard.tsx
import React, { useState } from 'react';

const steps = [
  { title: 'Welcome', content: 'Welcome to OpenChimera! Let\'s get you set up.' },
  { title: 'Connect Backend', content: 'Connect to your OpenChimera backend.' },
  { title: 'Configure Plugins', content: 'Select and configure plugins.' },
  { title: 'Finish', content: 'You\'re ready to go!' },
];

export default function OnboardingWizard() {
  const [step, setStep] = useState(0);
  return (
    <div className="max-w-lg mx-auto p-6 bg-white rounded shadow">
      <h2 className="text-2xl font-bold mb-4">{steps[step].title}</h2>
      <p className="mb-6">{steps[step].content}</p>
      <div className="flex justify-between">
        <button
          className="btn"
          onClick={() => setStep(s => Math.max(0, s - 1))}
          disabled={step === 0}
        >Back</button>
        <button
          className="btn btn-primary"
          onClick={() => setStep(s => Math.min(steps.length - 1, s + 1))}
          disabled={step === steps.length - 1}
        >{step === steps.length - 1 ? 'Done' : 'Next'}</button>
      </div>
    </div>
  );
}
