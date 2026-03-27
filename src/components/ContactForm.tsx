"use client";

import { useState, FormEvent, useEffect } from "react";

interface ContactFormProps {
  prefillDomain?: string;
}

const subjects = [
  "Buy a Domain",
  "Sell a Domain",
  "Partnership Inquiry",
  "General",
];

export default function ContactForm({ prefillDomain }: ContactFormProps) {
  const [submitted, setSubmitted] = useState(false);
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [subject, setSubject] = useState(prefillDomain ? "Buy a Domain" : "General");
  const [message, setMessage] = useState(
    prefillDomain ? `I am interested in acquiring ${prefillDomain}.\n\n` : ""
  );

  useEffect(() => {
    if (prefillDomain) {
      setSubject("Buy a Domain");
      setMessage(`I am interested in acquiring ${prefillDomain}.\n\n`);
    }
  }, [prefillDomain]);

  function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setSubmitted(true);
  }

  if (submitted) {
    return (
      <div className="bg-surface rounded-lg shadow-sm border border-border p-8 text-center">
        <h3 className="text-xl font-semibold text-charcoal mb-2">
          Thank you for reaching out
        </h3>
        <p className="text-muted text-sm">
          We have received your message and will respond within one business day.
        </p>
      </div>
    );
  }

  return (
    <form
      onSubmit={handleSubmit}
      className="bg-surface rounded-lg shadow-sm border border-border p-8"
    >
      <div className="space-y-5">
        {/* Name */}
        <div>
          <label htmlFor="contact-name" className="block text-sm font-medium text-charcoal mb-1.5">
            Name
          </label>
          <input
            id="contact-name"
            type="text"
            required
            value={name}
            onChange={(e) => setName(e.target.value)}
            className="w-full px-4 py-2.5 border border-border rounded text-sm text-charcoal bg-background focus:outline-none focus:ring-2 focus:ring-gold/50 focus:border-gold transition-colors"
            placeholder="Your name"
          />
        </div>

        {/* Email */}
        <div>
          <label htmlFor="contact-email" className="block text-sm font-medium text-charcoal mb-1.5">
            Email
          </label>
          <input
            id="contact-email"
            type="email"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            className="w-full px-4 py-2.5 border border-border rounded text-sm text-charcoal bg-background focus:outline-none focus:ring-2 focus:ring-gold/50 focus:border-gold transition-colors"
            placeholder="you@company.com"
          />
        </div>

        {/* Subject */}
        <div>
          <label htmlFor="contact-subject" className="block text-sm font-medium text-charcoal mb-1.5">
            Subject
          </label>
          <select
            id="contact-subject"
            required
            value={subject}
            onChange={(e) => setSubject(e.target.value)}
            className="w-full px-4 py-2.5 border border-border rounded text-sm text-charcoal bg-background focus:outline-none focus:ring-2 focus:ring-gold/50 focus:border-gold transition-colors appearance-none"
          >
            {subjects.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        </div>

        {/* Message */}
        <div>
          <label htmlFor="contact-message" className="block text-sm font-medium text-charcoal mb-1.5">
            Message
          </label>
          <textarea
            id="contact-message"
            required
            rows={5}
            value={message}
            onChange={(e) => setMessage(e.target.value)}
            className="w-full px-4 py-2.5 border border-border rounded text-sm text-charcoal bg-background focus:outline-none focus:ring-2 focus:ring-gold/50 focus:border-gold transition-colors resize-vertical"
            placeholder="How can we help?"
          />
        </div>

        {/* Submit */}
        <button
          type="submit"
          className="w-full bg-gold text-charcoal font-medium text-sm px-6 py-3 rounded hover:opacity-90 transition-opacity"
        >
          Send Message
        </button>
      </div>
    </form>
  );
}
