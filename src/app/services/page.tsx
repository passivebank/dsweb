import type { Metadata } from "next";
import Link from "next/link";

export const metadata: Metadata = {
  title: "Services — DomainSnobs",
  description:
    "Infrastructure-grade domain services for investors, brands, and holding companies.",
};

const services = [
  {
    icon: "\u25C8",
    headline: "Domain Acquisition",
    body: "We source expiring, dropped, and off-market domains using proprietary scoring and monitoring infrastructure. Our multi-registrar submission architecture operates across seven acquisition channels with sub-second execution. Domains are evaluated on estimated traffic value, backlink authority, keyword equity, and commercial intent before any capital is deployed.",
  },
  {
    icon: "\u2194",
    headline: "Domain Brokerage",
    body: "Confidential buy-side and sell-side representation for premium domain transactions. We handle outreach, negotiation, and settlement. All brokered transactions settle through Escrow.com with standard ICANN transfer protocols. Our client list includes funded startups, public companies, and private equity portfolio brands.",
  },
  {
    icon: "\u25A3",
    headline: "Portfolio Consulting",
    body: "Domain strategy advisory for investors and holding companies managing 50+ domain portfolios. Services include portfolio valuation using comparable sales data, renewal optimization, acquisition pipeline design, and marketplace positioning across Afternic, Sedo, and Dan.com.",
  },
  {
    icon: "\u2261",
    headline: "Domain Valuation",
    body: "Independent domain appraisal using a multi-signal scoring model. We evaluate estimated traffic value, backlink equity profile, keyword commercial intent, comparable sales history, and brandability metrics. Reports include acquisition price range, estimated resale ceiling, and recommended hold strategy.",
  },
];

export default function ServicesPage() {
  return (
    <>
      {/* Hero */}
      <section className="bg-charcoal text-white py-20">
        <div className="max-w-7xl mx-auto px-6">
          <h1 className="text-4xl font-bold tracking-tight">Services</h1>
          <p className="mt-4 text-lg text-gray-400 max-w-2xl">
            Infrastructure-grade domain services for investors, brands, and holding companies.
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
              {/* Icon */}
              <div className="flex-shrink-0 w-14 h-14 rounded-lg bg-gold/10 text-gold flex items-center justify-center text-2xl font-bold">
                {service.icon}
              </div>

              {/* Content */}
              <div className="flex-1">
                <h2 className="text-2xl font-bold text-charcoal">
                  {service.headline}
                </h2>
                <p className="mt-4 text-slate leading-relaxed max-w-3xl">
                  {service.body}
                </p>
                <Link
                  href="/contact"
                  className="inline-block mt-6 text-sm font-medium text-gold hover:text-gold-dark transition-colors"
                >
                  Get Started &rarr;
                </Link>
              </div>
            </div>
          </div>
        </section>
      ))}

      {/* Bottom CTA */}
      <section className="bg-charcoal text-white py-20">
        <div className="max-w-7xl mx-auto px-6 text-center">
          <h2 className="text-3xl font-bold tracking-tight">
            Ready to discuss your domain strategy?
          </h2>
          <Link
            href="/contact"
            className="inline-block mt-8 bg-gold text-charcoal text-sm font-medium px-8 py-3 rounded hover:opacity-90 transition-opacity"
          >
            Contact Us
          </Link>
        </div>
      </section>
    </>
  );
}
