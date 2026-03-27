import type { Metadata } from "next";
import Link from "next/link";

export const metadata: Metadata = {
  title: "About — DomainSnobs",
  description:
    "Domain investment and brokerage firm specializing in high-authority expired domains and premium domain transactions since 2017.",
};

const capabilities = [
  {
    title: "Multi-Registrar Architecture",
    description:
      "Seven acquisition channels across four registrars with sub-second EPP submission capability.",
  },
  {
    title: "Proprietary Scoring",
    description:
      "40+ signal evaluation model covering traffic, authority, keywords, and comparable sales.",
  },
  {
    title: "Geographic Distribution",
    description:
      "Acquisition nodes across three data centers for competitive drop-catch timing.",
  },
];

export default function AboutPage() {
  return (
    <>
      {/* Hero */}
      <section className="bg-charcoal py-24">
        <div className="max-w-7xl mx-auto px-6 text-center">
          <p className="text-gold text-sm font-medium tracking-[0.2em] uppercase mb-4">
            About
          </p>
          <h1 className="text-4xl md:text-5xl font-bold text-white tracking-tight">
            We set the bar. Then we raise it.
          </h1>
          <p className="mt-6 text-gray-400 text-lg max-w-2xl mx-auto">
            DomainSnobs is a domain investment and brokerage firm. Founded in 2017. Selective by design.
          </p>
        </div>
      </section>

      {/* Content */}
      <section className="bg-surface py-16 md:py-24">
        <div className="max-w-3xl mx-auto px-6">
          <p className="text-slate text-base leading-relaxed mb-6">
            We specialize in acquiring high-authority expired domains and brokering premium domain
            transactions across the .com, .net, .io, and ccTLD markets. We have been active in the
            domain aftermarket since 2016, building acquisition systems that identify undervalued
            domain equity before it reaches the open market.
          </p>

          <p className="text-slate text-base leading-relaxed mb-12">
            The name says it all. We are particular about what we acquire, how we evaluate it, and who
            we work with. Every domain in our portfolio cleared a scoring threshold that most investors
            don&apos;t even measure. That selectivity is not a limitation — it is the entire strategy.
          </p>

          {/* Manifesto Block */}
          <div className="bg-charcoal rounded-lg p-8 md:p-12 mb-12">
            <p className="text-gold text-sm font-medium tracking-[0.15em] uppercase mb-4">
              Our Position
            </p>
            <p className="text-white text-xl md:text-2xl font-medium leading-relaxed">
              We believe domain equity is undervalued by the market. Our systems identify that gap
              before anyone else does. We don&apos;t speculate on trends or brandability alone. Our
              positions are backed by traffic data, link equity, and verifiable commercial intent.
            </p>
            <div className="mt-6 w-12 h-0.5 bg-gold" />
          </div>

          <h2 className="text-2xl font-bold text-charcoal mb-4">
            How We Work
          </h2>

          <p className="text-slate text-base leading-relaxed mb-6">
            Our acquisition pipeline evaluates domains across 40+ signals including estimated traffic
            value, backlink authority profile, keyword commercial intent, comparable sales data, and
            brandability metrics. We operate multi-registrar infrastructure across seven acquisition
            channels with geographic distribution for competitive drop-catch execution.
          </p>

          <p className="text-slate text-base leading-relaxed mb-12">
            If a domain doesn&apos;t score above our threshold on all three independent models, we
            pass. No exceptions, no &ldquo;gut feeling&rdquo; overrides, no optimism-driven holds.
            The data decides. That discipline is why our portfolio performs.
          </p>

          <h2 className="text-2xl font-bold text-charcoal mb-8">
            Infrastructure
          </h2>

          <div className="grid md:grid-cols-3 gap-6 mb-16">
            {capabilities.map((cap) => (
              <div
                key={cap.title}
                className="border-t-2 border-gold pt-4"
              >
                <h3 className="text-base font-bold text-charcoal mb-2">
                  {cap.title}
                </h3>
                <p className="text-sm text-muted leading-relaxed">
                  {cap.description}
                </p>
              </div>
            ))}
          </div>

          {/* CTA */}
          <div className="text-center border-t border-border pt-12">
            <p className="text-lg text-charcoal font-medium mb-2">
              Selective about partners, too.
            </p>
            <p className="text-muted text-sm mb-6">
              If you have inventory worth discussing or a name worth pursuing, we&apos;re listening.
            </p>
            <Link
              href="/contact"
              className="inline-block bg-gold text-charcoal font-semibold text-sm px-8 py-3.5 rounded hover:bg-gold-light transition-colors tracking-wide"
            >
              Get in Touch
            </Link>
          </div>
        </div>
      </section>
    </>
  );
}
