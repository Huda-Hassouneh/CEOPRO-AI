// import type {
//   PayPalBillingPlan,
//   PayPalPlanDetails,
//   PayPalProduct,
//   PayPalService
// } from "../../../types/Payment Providers/paypal.js";

// // Generates a PayPal OAuth access token for authenticated API requests.
// async function generateAccessToken(): Promise<string> {
//   const CLIENT_ID = process.env.PAYPAL_CLIENT_ID;
//   const CLIENT_SECRET = process.env.PAYPAL_CLIENT_SECRET;
//   const BASE_URL = process.env.PAYPAL_BASE_URL;

//   if (!CLIENT_ID) {
//     throw new Error("PAYPAL_CLIENT_ID is not configured");
//   }

//   if (!CLIENT_SECRET) {
//     throw new Error("PAYPAL_CLIENT_SECRET is not configured");
//   }

//   if (!BASE_URL) {
//     throw new Error("PAYPAL_BASE_URL is not configured");
//   }

//   const auth = Buffer.from(`${CLIENT_ID}:${CLIENT_SECRET}`).toString("base64");

//   const url = `${BASE_URL}/v1/oauth2/token`;

//   try {
//     const response = await fetch(url, {
//       method: "POST",
//       headers: {
//         Authorization: `Basic ${auth}`,
//         "Content-Type": "application/x-www-form-urlencoded",
//         Accept: "application/json"
//       },
//       body: "grant_type=client_credentials"
//     });

//     const contentType = response.headers.get("content-type");

//     const result = contentType?.includes("application/json")
//       ? await response.json()
//       : await response.text();

//     if (!response.ok) {
//       console.error("PayPal OAuth request failed:", {
//         status: response.status,
//         statusText: response.statusText,
//         result
//       });

//       throw new Error(
//         `PayPal OAuth failed (${response.status}): ${
//           typeof result === "string" ? result : JSON.stringify(result)
//         }`
//       );
//     }

//     if (
//       typeof result !== "object" ||
//       result === null ||
//       !("access_token" in result) ||
//       typeof result.access_token !== "string"
//     ) {
//       throw new Error("PayPal OAuth response did not contain an access token");
//     }

//     return result.access_token;
//   } catch (error) {
//     if (error instanceof TypeError) {
//       console.error("Unable to connect to PayPal:", error);
//       throw new Error("Unable to connect to PayPal");
//     }

//     throw error;
//   }
// }

// // Creates the CEOPRO AI Platform product in the PayPal catalog.
// async function createCatalog(
//   accessToken: string,
//   payload = {
//     name: "CEOPRO AI Platform",
//     description: "AI-powered business intelligence and advisory platform",
//     type: "SERVICE",
//     category: "SOFTWARE"
//   }
// ): Promise<PayPalProduct> {
//   if (!accessToken) {
//     throw new Error("PayPal access token is required");
//   }

//   const baseUrl = process.env.PAYPAL_BASE_URL;

//   if (!baseUrl) {
//     throw new Error("PAYPAL_BASE_URL is not configured");
//   }

//   const url = `${baseUrl}/v1/catalogs/products`;

//   try {
//     const response = await fetch(url, {
//       method: "POST",
//       headers: {
//         Authorization: `Bearer ${accessToken}`,
//         "Content-Type": "application/json",
//         Accept: "application/json"
//       },
//       body: JSON.stringify(payload)
//     });

//     const contentType = response.headers.get("content-type");

//     const result = contentType?.includes("application/json")
//       ? await response.json()
//       : await response.text();

//     if (!response.ok) {
//       console.error("PayPal create catalog failed:", {
//         status: response.status,
//         statusText: response.statusText,
//         result
//       });

//       throw new Error(
//         `PayPal catalog creation failed (${response.status}): ${
//           typeof result === "string" ? result : JSON.stringify(result)
//         }`
//       );
//     }

//     return result as PayPalProduct;
//   } catch (error) {
//     if (error instanceof TypeError) {
//       console.error("PayPal request failed:", error);
//       throw new Error("Unable to connect to PayPal");
//     }

//     throw error;
//   }
// }

// // Creates a PayPal billing plan associated with a CEOPRO product.
// async function createPlan(
//   accessToken: string,
//   productId: string,
//   planDetails: PayPalPlanDetails
// ): Promise<PayPalBillingPlan> {
//   if (!accessToken) {
//     throw new Error("PayPal access token is required");
//   }

//   if (!productId) {
//     throw new Error("PayPal product ID is required");
//   }

//   const baseUrl = process.env.PAYPAL_BASE_URL;

//   if (!baseUrl) {
//     throw new Error("PAYPAL_BASE_URL is not configured");
//   }

//   const { name, description, trialConfig, regularConfig } = planDetails;

//   const billingCycles = [];

//   if (trialConfig) {
//     billingCycles.push({
//       frequency: {
//         interval_unit: trialConfig.interval_unit,
//         interval_count: trialConfig.interval_count
//       },
//       tenure_type: "TRIAL",
//       sequence: 1,
//       total_cycles: trialConfig.total_cycles,
//       pricing_scheme: {
//         fixed_price: {
//           value: "0.00",
//           currency_code: trialConfig.currency_code
//         }
//       }
//     });
//   }

//   billingCycles.push({
//     frequency: {
//       interval_unit: regularConfig.interval_unit,
//       interval_count: regularConfig.interval_count
//     },
//     tenure_type: "REGULAR",
//     sequence: trialConfig ? 2 : 1,
//     total_cycles: regularConfig.total_cycles,
//     pricing_scheme: {
//       fixed_price: {
//         value: regularConfig.price.toString(),
//         currency_code: regularConfig.currency_code
//       }
//     }
//   });

//   const payload = {
//     product_id: productId,
//     name,
//     description,
//     billing_cycles: billingCycles,
//     payment_preferences: {
//       auto_bill_outstanding: true,
//       payment_failure_threshold: 3
//     }
//   };

//   const url = `${baseUrl}/v1/billing/plans`;

//   try {
//     const response = await fetch(url, {
//       method: "POST",
//       headers: {
//         Authorization: `Bearer ${accessToken}`,
//         "Content-Type": "application/json",
//         Accept: "application/json"
//       },
//       body: JSON.stringify(payload)
//     });

//     const contentType = response.headers.get("content-type");

//     const result = contentType?.includes("application/json")
//       ? await response.json()
//       : await response.text();

//     if (!response.ok) {
//       console.error("PayPal plan creation failed:", {
//         status: response.status,
//         statusText: response.statusText,
//         result
//       });

//       throw new Error(
//         `PayPal plan creation failed (${response.status}): ${
//           typeof result === "string" ? result : JSON.stringify(result)
//         }`
//       );
//     }

//     return result as PayPalBillingPlan;
//   } catch (error) {
//     if (error instanceof TypeError) {
//       console.error("Unable to connect to PayPal:", error);

//       //   throw new Error("Unable to connect to PayPal");
//     }

//     throw error;
//   }
// }

// // Performs the one-time PayPal onboarding setup for CEOPRO.
// async function paypalOnBoarding(): Promise<PayPalProduct> {
//   const token = await generateAccessToken();
//   return createCatalog(token);
// }

// export const paypalService: PayPalService = {
//   generateAccessToken,
//   createCatalog,
//   createPlan,
//   paypalOnBoarding
// };
