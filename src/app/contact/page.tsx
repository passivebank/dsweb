"use client";

import { Suspense } from "react";
import { useSearchParams } from "next/navigation";
import ContactForm from "@/components/ContactForm";

function ContactContent() {
  const searchParams = useSearchParams();
  const domain = searchParams.get("domain") || undefined;

  return (
    <>
      {/* Hero */}
      <section className="bg-charcoal py-20">
        <div className="max-w-7xl mx-auto px-6 text-center">
          <h1 className="text-4xl md:text-5xl font-bold text-white tracking-tight">
            Contact
          </h1>
          <p className="mt-4 text-lg text-gray-400 max-w-2xl mx-auto">
            For domain inquiries, partnership discussions, or general questions.
          </p>
        </div>
      </section>

      {/* Form + Info */}
      <section className="bg-background py-16 md:py-24">
        <div className="max-w-2xl mx-auto px-6">
          <ContactForm prefillDomain={domain} />

          <div className="mt-12 space-y-6 text-sm">
            <div>
              <h3 className="font-medium text-charcoal mb-1">Email</h3>
              <a
                href="mailto:acquisitions@domainsnobs.com"
                className="text-muted hover:text-charcoal transition-colors"
              >
                acquisitions@domainsnobs.com
              </a>
            </div>

            <div>
              <h3 className="font-medium text-charcoal mb-1">Location</h3>
              <p className="text-muted">
                Atlanta, GA — Operating across North American and European
                domain markets
              </p>
            </div>

            <div className="border-t border-border pt-6">
              <p className="text-muted">
                For partnership and infrastructure inquiries, select Partnership
                Inquiry above.
              </p>
            </div>
          </div>
        </div>
      </section>
    </>
  );
}

export default function ContactPage() {
  return (
    <Suspense
      fallback={
        <div className="bg-charcoal py-20">
          <div className="max-w-7xl mx-auto px-6 text-center">
            <h1 className="text-4xl md:text-5xl font-bold text-white tracking-tight">
              Contact
            </h1>
          </div>
        </div>
      }
    >
      <ContactContent />
    </Suspense>
  );
}
