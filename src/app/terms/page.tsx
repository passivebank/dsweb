import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Terms of Service — DomainSnobs",
  description:
    "Terms of service for DomainSnobs LLC, a domain investment and brokerage firm.",
};

export default function TermsPage() {
  return (
    <>
      {/* Hero */}
      <section className="bg-charcoal py-20">
        <div className="max-w-7xl mx-auto px-6 text-center">
          <h1 className="text-4xl md:text-5xl font-bold text-white tracking-tight">
            Terms of Service
          </h1>
        </div>
      </section>

      {/* Content */}
      <section className="bg-surface py-16 md:py-24">
        <div className="max-w-3xl mx-auto px-6 prose-custom">
          <p className="text-muted text-sm mb-12">
            Effective date: January 1, 2025
          </p>

          <h2 className="text-xl font-semibold text-charcoal mb-3">
            Acceptance of Terms
          </h2>
          <p className="text-slate text-base leading-relaxed mb-10">
            By accessing or using the DomainSnobs website and services, you
            agree to be bound by these Terms of Service. If you do not agree to
            these terms, you should not use our website or engage our services.
            DomainSnobs LLC reserves the right to update these terms at any time.
            Continued use of the site following any changes constitutes
            acceptance of those changes.
          </p>

          <h2 className="text-xl font-semibold text-charcoal mb-3">
            Services Description
          </h2>
          <p className="text-slate text-base leading-relaxed mb-4">
            DomainSnobs LLC provides domain investment, acquisition, and
            brokerage services. Our services include identifying and acquiring
            high-authority expired domains, brokering domain sales between
            buyers and sellers, and providing domain valuation consulting.
          </p>
          <p className="text-slate text-base leading-relaxed mb-10">
            Domain listings, valuations, and market analyses presented on this
            website are provided for informational purposes. While we endeavor
            to ensure accuracy, domain valuations are estimates based on
            available market data and are not guarantees of sale price or
            investment return.
          </p>

          <h2 className="text-xl font-semibold text-charcoal mb-3">
            Domain Transactions
          </h2>
          <p className="text-slate text-base leading-relaxed mb-4">
            All domain transactions facilitated by DomainSnobs LLC are subject
            to the terms and conditions of the applicable registrar and escrow
            service. We recommend that all transactions above $1,000 be
            conducted through a licensed escrow service such as Escrow.com.
          </p>
          <p className="text-slate text-base leading-relaxed mb-4">
            Domain transfers are subject to ICANN transfer policies, including
            the 60-day transfer lock following a change of registrant. Buyers
            are responsible for verifying domain status, transfer eligibility,
            and any applicable transfer fees prior to completing a transaction.
          </p>
          <p className="text-slate text-base leading-relaxed mb-10">
            DomainSnobs LLC does not guarantee the availability of any domain
            listed on this website. Domain availability is subject to change
            without notice due to the nature of the domain aftermarket.
          </p>

          <h2 className="text-xl font-semibold text-charcoal mb-3">
            Limitation of Liability
          </h2>
          <p className="text-slate text-base leading-relaxed mb-4">
            DomainSnobs LLC provides its services on an &ldquo;as is&rdquo; and
            &ldquo;as available&rdquo; basis. We make no warranties, express or
            implied, regarding the accuracy of domain valuations, the outcome of
            domain transactions, or the suitability of any domain for a
            particular purpose.
          </p>
          <p className="text-slate text-base leading-relaxed mb-10">
            In no event shall DomainSnobs LLC be liable for any indirect,
            incidental, special, consequential, or punitive damages arising out
            of or related to your use of our services, including but not limited
            to lost profits, lost data, or business interruption, regardless of
            the theory of liability.
          </p>

          <h2 className="text-xl font-semibold text-charcoal mb-3">
            Governing Law
          </h2>
          <p className="text-slate text-base leading-relaxed mb-10">
            These Terms of Service shall be governed by and construed in
            accordance with the laws of the State of Georgia, without regard to
            its conflict of law provisions. Any disputes arising under these
            terms shall be subject to the exclusive jurisdiction of the state
            and federal courts located in Fulton County, Georgia.
          </p>

          <h2 className="text-xl font-semibold text-charcoal mb-3">
            Contact
          </h2>
          <p className="text-slate text-base leading-relaxed">
            For questions regarding these terms, contact DomainSnobs LLC at{" "}
            <a
              href="mailto:ben@domainsnobs.com"
              className="text-charcoal font-medium hover:text-gold transition-colors"
            >
              ben@domainsnobs.com
            </a>
            .
          </p>
        </div>
      </section>
    </>
  );
}
