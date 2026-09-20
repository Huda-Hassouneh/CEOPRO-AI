import Stripe from "stripe";
import {
  CustomerWithClockParams,
  SimulationParams,
  SimulationResult
} from "../../../../../DTO/stripe.dto.js";

const stripe = new Stripe(process.env.STRIPE_SECRET_KEY as string);

async function updateToValidPaymentMethod(
  customerId: string,
  subscriptionId: string
) {
  // 1. Create a valid test card payment method (Standard Visa)
  const validPaymentMethod = await stripe.paymentMethods.create({
    type: "card",
    card: {
      token: "tok_visa" // Or card object: { number: '4242424242424242', exp_month: 12, exp_year: 2028, cvc: '123' }
    }
  });

  // 2. Attach the payment method to the customer
  await stripe.paymentMethods.attach(validPaymentMethod.id, {
    customer: customerId
  });

  // 3. Set it as the default invoice payment method on the customer
  await stripe.customers.update(customerId, {
    invoice_settings: {
      default_payment_method: validPaymentMethod.id
    }
  });

  // 4. Update the subscription directly (critical if the sub had its own pinned card)
  await stripe.subscriptions.update(subscriptionId, {
    default_payment_method: validPaymentMethod.id
  });

  console.log(
    `Payment method updated to ${validPaymentMethod.id} successfully.`
  );
  return validPaymentMethod;
}
/**
 * Creates a new Test Clock initialized at a specific timestamp.
 */
export async function createTestClock(
  name: string = "Simulation Clock",
  frozenTime: number = Math.floor(Date.now() / 1000)
): Promise<Stripe.TestHelpers.TestClock> {
  return stripe.testHelpers.testClocks.create({
    name,
    frozen_time: frozenTime
  });
}

/**
 * Creates a customer attached to a specific Test Clock with an active default payment method.
 */
export async function createCustomerWithClock({
  email,
  name,
  testClockId,
  paymentMethodId = "pm_card_visa"
}: CustomerWithClockParams): Promise<Stripe.Customer> {
  const customer = await stripe.customers.create({
    email,
    name,
    test_clock: testClockId
  });

  const paymentMethod = await stripe.paymentMethods.attach(paymentMethodId, {
    customer: customer.id
  });

  return stripe.customers.update(customer.id, {
    invoice_settings: {
      default_payment_method: paymentMethod.id
    }
  });
}

/**
 * Advances a test clock by a designated number of days.
 */
export async function advanceClockDays(
  testClockId: string,
  days: number = 31
): Promise<Stripe.TestHelpers.TestClock> {
  const clock = await stripe.testHelpers.testClocks.retrieve(testClockId);
  const targetTime = clock.frozen_time + days * 24 * 60 * 60;

  return stripe.testHelpers.testClocks.advance(testClockId, {
    frozen_time: targetTime
  });
}

/**
 * High-level orchestration: provisions a clock, customer, recurring subscription,
 * and fast-forwards the clock to trigger billing renewal.
 */
export async function runSubscriptionSimulation({
  priceId,
  customerEmail,
  customerName = "Test User",
  advanceDays = 31
}: SimulationParams): Promise<SimulationResult> {
  const clock = await createTestClock(`Sim: ${customerEmail}`);

  const customer = await createCustomerWithClock({
    name: customerName,
    email: customerEmail,
    testClockId: clock.id
  });

  const subscription = await stripe.subscriptions.create({
    customer: customer.id,
    items: [{ price: priceId }]
  });

  const advancedClock = await advanceClockDays(clock.id, advanceDays);

  return {
    testClockId: clock.id,
    customerId: customer.id,
    subscriptionId: subscription.id,
    advancedTo: advancedClock.frozen_time
  };
}

async function getClockTime(clockId: string): Promise<Date> {
  const clock = await stripe.testHelpers.testClocks.retrieve(clockId);

  // frozen_time is a Unix timestamp in seconds
  const simulatedDate = new Date(clock.frozen_time * 1000);

  console.log(`Unix Seconds: ${clock.frozen_time}`);
  console.log(`Simulated ISO Date: ${simulatedDate.toISOString()}`);

  return simulatedDate;
}

// advanceClockDays("clock_1UHlRBDvEnSheKuc4ymTQI9Q", 181);

// console.log(await getClockTime("clock_1UG42gDvEnSheKucSJs8aOuc"));

// Attach declining card
// const decliningCard = await stripe.paymentMethods.attach(
//   "pm_card_chargeCustomerFail",
//   {
//     customer: "cus_VGcKuVoiF4BKS8"
//   }
// );

// // Set as customer default for recurring invoices
// await stripe.customers.update("cus_VGcKuVoiF4BKS8", {
//   invoice_settings: {
//     default_payment_method: decliningCard.id
//   }
// });
// 1. Attach the failing card to the customer
// const failingPaymentMethod = await stripe.paymentMethods.attach(
//   "pm_card_chargeCustomerFail",
//   { customer: "cus_VGcKuVoiF4BKS8" }
// );

// 2. Update BOTH the subscription AND the customer
// await Promise.all([
//   // Update the customer default
//   stripe.customers.update("cus_VGcKuVoiF4BKS8", {
//     invoice_settings: {
//       default_payment_method: failingPaymentMethod.id
//     }
//   }),
//   // Update the subscription directly (CRITICAL)
//   stripe.subscriptions.update("sub_1UG562DvEnSheKucitvmjlB1", {
//     default_payment_method: failingPaymentMethod.id
//   })
// ]);

// updateToValidPaymentMethod(
//   "cus_VGcKuVoiF4BKS8",
//   "sub_1UG562DvEnSheKucitvmjlB1"
// ).catch((err) => console.log(err));
