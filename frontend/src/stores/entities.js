import {nodesAPI,scenariosAPI,drillsAPI,proofsAPI} from '../api/entities.js';
export const store={nodes:[],scenarios:[],drills:[],proofs:[],proofStatus:{version:0,nodes:[]},async refresh(){[this.nodes,this.scenarios,this.drills,this.proofs,this.proofStatus]=await Promise.all([nodesAPI.list(),scenariosAPI.list(),drillsAPI.list(),proofsAPI.list(),proofsAPI.status()]);}};
