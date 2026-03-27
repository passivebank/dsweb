import type { Metadata } from "next";
import Link from "next/link";

export const metadata: Metadata = {
  title: "Services — DomainSnobs",
  description:
    "Infrastructure-grade domain services for investors, brands, and holding companies.",
};

const services = [
  {
    number: "01",
    headline: "Domain Acquisition",
    tagline: "We get there first.",
    body: "We source expiring, dropped, and off-market domains using proprietary scoring and monitoring infrastructure. Our multi-registrar submission architecture operates across seven acquisition channels with sub-second execution. Domains are evaluated on estimated traffic value, backlink authority, keyword equity, and commercial intent before any capital is deployed. If it doesn't meet the threshold, we don't touch it.",
  },
  {
    number: "02",
    headline: "Domain Brokerage",
    tagline: "Your name. Our network.",
    body: "Confidential buy-side and sell-side representation for premium domain transactions. We handle outreach, negotiation, and settlement. All brokered transactions settle through Escrow.com with standard ICANN transfer protocols. Our client list includes funded startups, public companies, and private equity portfolio brands. Discretion is default.",
  },
  {
    number: "03",
    headline: "Portfolio Consulting",
    tagline: "Data over intuition. Always.",
    body: "Domain strategy advisory for investors and holding companies managing 50+ domain portfolios. Services include portfolio valuation using comparable sales data, renewal optimization, acquisition pipeline design, and marketplace positioning across Afternic, Sedo, and Dan.com. We tell you what to drop, what to hold, and what to double down on.",
  },
  {
    number: "04",
    headline: "Domain Valuation",
    tagline: "What it's actually worth.",
    body: "Independent domain appraisal using a multi-signal scoring model. We evaluate estimated traffic value, backlink equity profile, keyword commercial intent, comparable sales history, and brandability metrics. Reports include acquisition price range, estimated resale ceiling, and recommended hold strategy. No inflated numbers, no wishful thinking.",
  },
];

export default function ServicesPage() {
  return (
    <>
      {/* Hero */}
      <section className="bg-charcoal text-white py-24">
        <div className="max-w-7xl mx-auto px-6">
          <p className="text-gold text-sm font-medium tracking-[0.2em] uppercase mb-4">
            Services
          </p>
          <h1 className="text-4xl md:text-5xl font-bold tracking-tight max-w-3xl">
            Premium service for premium assets.
          </h1>
          <p className="mt-6 text-lg text-gray-400 max-w-2xl">
            Infrastructure-grade domain services for investors, brands, and holding companies
            that take their namespace seriously.
          </p>
        </div>
      </section>

      {/* Service Blocks */}
      {services.map((service, idx) => (
        <section
          key={service.headline}
          className={idx % 2 === 0 ? "bg-surface" : "bg-background"}
        >
          <div className="max-w-7xl mx-auto px-6 py-20">
            <div className="flex flex-col md:flex-row items-start gap-10">
              {/* Number */}
              <div className="flex-shrink-0">
                <span className="text-5xl font-bold text-gold/20">
                  {service.number}
                </span>
              </div>

              {/* Content */}
              <div className="flex-1">
                <h2 className="text-2xl font-bold text-charcoal">
                  {service.headline}
                </h2>
                <p className="mt-1 text-gold text-sm font-medium">
                  {service.tagline}
                </p>
                <p className="mt-4 text-slate leading-relaxed max-w-3xl">
                  {service.body}
                </p>
                <Link
                  href="/contact"
                  className="inline-block mt-6 text-sm font-medium text-gold hover:text-gold-dark transition-colors"
                >
                  Inquire &rarr;
                </Link>
              </div>
            </div>
          </div>
        </section>
      ))}

      {/* Bottom CTA */}
      <section className="bg-charcoal text-white py-24">
        <div className="max-w-7xl mx-auto px-6 text-center">
          <p className="text-gold text-sm font-medium tracking-[0.2em] uppercase mb-4">
            Ready?
          </p>
          <h2 className="text-3xl font-bold tracking-tight max-w-2xl mx-auto">
            If you&apos;re serious about domains, we should talk.
          </h2>
          <Link
            href="/contact"
            className="inline-block mt-10 bg-gold text-charcoal text-sm font-semibold px-8 py-3.5 rounded hover:bg-gold-light transition-colors tracking-wide"
          >
            Start a Conversation
          </Link>
        </div>
      </section>
    </>
  );
}
