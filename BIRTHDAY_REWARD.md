# Metropia Coffee Birthday Reward V1

## Policy
- 50% off one drink
- One reward per customer per calendar year
- Reward is issued on the customer's stored birthday
- Reward is valid for 7 days from issue
- Customer chooses exactly one drink from the cart
- Discount applies to one unit only, even if quantity > 1
- Reward cannot be combined with another promotion in this implementation
- Reward is marked used only after the order is successfully paid

## Customer flow
1. Customer saves birthday with `/birthday DD-MM`.
2. Daily birthday loop issues the reward and sends a birthday message.
3. At checkout, the customer can choose **Use my 50% birthday discount** or continue without it.
4. If used, the customer selects one drink from the cart.
5. The checkout total is reduced by 50% of that drink's price.
6. The reward is validated again at Telegram pre-checkout.
7. After successful payment (including confirmed cash payment), the reward is marked used.

## Example
Drink: Latte — 35,000 so'm
Birthday discount: 17,500 so'm
Customer pays: 17,500 so'm
