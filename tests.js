const assert = require('node:assert/strict');
const { getPriority, calculateRecoveryRate, calculateWorkload, baseAccounts } = require('./app.js');

function runTests() {
  assert.equal(getPriority(74), 'High');
  assert.equal(getPriority(46), 'Medium');
  assert.equal(getPriority(18), 'Low');

  const recovery = calculateRecoveryRate(baseAccounts);
  assert.equal(typeof recovery, 'number');
  assert.ok(recovery >= 0 && recovery <= 100);

  const workload = calculateWorkload(baseAccounts);
  assert.equal(typeof workload, 'object');
  assert.ok(Object.keys(workload).length > 0);

  console.log('All logic tests passed.');
}

runTests();
